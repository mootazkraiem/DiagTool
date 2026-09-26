using System;
using System.IO;
using System.Net;
using System.Net.Http;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using CANvision.Native.Models;
using CANvision.Native.Services;
using CANvision.Native.ViewModels;
using Newtonsoft.Json;
using Xunit;

namespace CANvision.Native.Tests;

/// <summary>
/// Step 12: a refused analysis must not look successful, the result names the model the
/// backend used, unresolved frames are reported, and model status reaches the selector.
/// </summary>
public sealed class AnalysisResultContractTests
{
    private sealed class FixedResponse : HttpMessageHandler
    {
        private readonly HttpStatusCode status;
        private readonly string body;
        public FixedResponse(HttpStatusCode status, string body) { this.status = status; this.body = body; }

        protected override Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken)
            => Task.FromResult(new HttpResponseMessage(status) { Content = new StringContent(body, Encoding.UTF8, "application/json") });
    }

    private static async Task<PythonAnalyzeResponse?> Analyze(HttpStatusCode status, string body, string modelId)
    {
        var file = Path.GetTempFileName();
        try
        {
            File.WriteAllText(file, "timestamp,can_id,b0\n0.0,100,1\n");
            var client = new PythonApiClient(new AppLogger(), new HttpClient(new FixedResponse(status, body)));
            return await client.AnalyzeLogsAsync(new[] { file }, CancellationToken.None, modelId);
        }
        finally
        {
            File.Delete(file);
        }
    }

    // ── P1-4: refusal keeps its status and reason ────────────────────────────

    [Fact]
    public async Task Http409_is_raised_with_status_and_backend_reason()
    {
        var error = await Assert.ThrowsAsync<PythonApiException>(() => Analyze(
            HttpStatusCode.Conflict,
            "{\"detail\":\"model 'mg_zs_ev' cannot be used for offline analysis: clean_held_back - held back\"}",
            "mg_zs_ev"));

        Assert.Equal(409, error.StatusCode);
        Assert.True(error.IsRefusal);
        Assert.Contains("clean_held_back", error.Detail);
    }

    [Fact]
    public async Task Http400_unknown_model_is_raised_not_swallowed()
    {
        var error = await Assert.ThrowsAsync<PythonApiException>(() => Analyze(
            HttpStatusCode.BadRequest, "{\"detail\":\"unknown model id 'no_such_vehicle'\"}", "no_such_vehicle"));
        Assert.Equal(400, error.StatusCode);
        Assert.Contains("no_such_vehicle", error.Detail);
    }

    [Fact]
    public void Refusal_text_never_says_complete()
    {
        var text = HomeViewModel.RefusalStatusText(new PythonApiException(409, "model 'mg_zs_ev' cannot be used\nsecond line"));
        Assert.StartsWith("ANALYSIS REFUSED (HTTP 409)", text);
        Assert.DoesNotContain("COMPLETE", text);
        Assert.DoesNotContain("SECOND LINE", text);
        Assert.StartsWith("ANALYSIS FAILED (HTTP 500)", HomeViewModel.RefusalStatusText(new PythonApiException(500, "boom")));
    }

    [Fact]
    public void No_summary_is_not_reported_as_a_completed_analysis()
        => Assert.DoesNotContain("COMPLETE", HomeViewModel.CompletionStatusText(null, "UNKNOWN", "kia_ev6"));

    // ── P1-7: the model actually used is displayed ───────────────────────────

    [Fact]
    public void Completion_names_the_backend_model_and_the_selection_when_they_differ()
    {
        var alias = new PythonAnalyzeSummary { ModelId = "general", RequestedModelId = "renault_zoe" };
        Assert.Equal("ANALYSIS COMPLETE — NORMAL · MODEL GENERAL (SELECTED RENAULT_ZOE)",
            HomeViewModel.CompletionStatusText(alias, "NORMAL", "renault_zoe"));

        var clean = new PythonAnalyzeSummary { ModelId = "kia_ev6", RequestedModelId = "kia_ev6" };
        Assert.Equal("ANALYSIS COMPLETE — NORMAL · MODEL KIA_EV6", HomeViewModel.CompletionStatusText(clean, "NORMAL", "kia_ev6"));
    }

    // ── P1-6: unresolved frames reach the client ─────────────────────────────

    [Fact]
    public async Task Summary_carries_scored_and_unresolved_counts()
    {
        const string body = "{\"summary\":{\"files_received\":1,\"rows_parsed\":491969,\"anomaly_count\":2951," +
                            "\"normal_count\":488846,\"cluster_count\":2,\"parse_lines_total\":0,\"parse_lines_parsed\":0," +
                            "\"parse_lines_skipped\":0,\"elapsed_ms\":1.0,\"model_id\":\"nissan_leaf_2019\",\"model_kind\":\"vehicle\"," +
                            "\"unresolved_count\":172,\"unresolved_reasons\":{\"warmup\":148,\"sparse_id\":24}," +
                            "\"scored_count\":491797,\"requested_model_id\":\"nissan_leaf_2019\"," +
                            "\"model_status\":\"clean_holdout_evaluated\"},\"anomalies\":[]}";
        var response = await Analyze(HttpStatusCode.OK, body, "nissan_leaf_2019");
        var s = response!.Summary!;

        Assert.Equal(491797, s.ScoredCount);
        Assert.Equal(172, s.UnresolvedCount);
        Assert.Equal(148, s.UnresolvedReasons["warmup"]);
        Assert.Equal(24, s.UnresolvedReasons["sparse_id"]);
        Assert.Equal(s.RowsParsed, s.ScoredCount + s.UnresolvedCount);
        Assert.Equal(s.ScoredCount, s.AnomalyCount + s.NormalCount);
        Assert.Equal("clean_holdout_evaluated", s.ModelStatus);
    }

    // ── P1-5: model status reaches the selector ──────────────────────────────

    [Theory]
    [InlineData("clean_holdout_evaluated", "clean_2", "clean_2", "CLEAN-2 · HOLDOUT EVALUATED", "READY")]
    [InlineData("clean_unvalidated_no_holdout", "refused", "legacy", "CLEAN-2 NOT PROMOTED · UNVALIDATED", "LEGACY")]
    [InlineData("clean_held_back", "refused", "refused", "CLEAN-2 HELD BACK", "UNAVAILABLE")]
    [InlineData("unavailable_no_clean_model", "refused", "refused", "NO CLEAN MODEL", "UNAVAILABLE")]
    [InlineData("legacy", "refused", "legacy", "LEGACY MODEL", "LEGACY")]
    public void Model_status_is_shown_not_implied(string status, string offline, string live, string kindText, string statusText)
    {
        var info = JsonConvert.DeserializeObject<TrainedModelInfo>(
            $"{{\"id\":\"x\",\"name\":\"X\",\"kind\":\"trained\",\"model_id\":\"x\",\"states\":[],\"has_dbc\":false," +
            $"\"status\":\"{status}\",\"offline\":\"{offline}\",\"live\":\"{live}\"}}")!;
        Assert.Equal(kindText, info.KindText);
        Assert.Equal(statusText, info.StatusText);
        Assert.Equal(offline == "refused", info.OfflineRefused);
    }
}
