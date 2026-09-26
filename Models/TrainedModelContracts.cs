using System.Collections.Generic;
using Newtonsoft.Json;

namespace CANvision.Native.Models;

/// <summary>
/// One selectable vehicle / AI model, as listed by the backend's <c>GET /api/models</c>.
/// </summary>
public sealed class TrainedModelInfo
{
    /// <summary>Selection id sent to the analysis pipeline as the vehicle / model id.</summary>
    [JsonProperty("id")]
    public string Id { get; set; } = string.Empty;

    [JsonProperty("name")]
    public string Name { get; set; } = string.Empty;

    /// <summary>"general", "trained" (vehicle model) or "profile" (DBC profile without its own model).</summary>
    [JsonProperty("kind")]
    public string Kind { get; set; } = string.Empty;

    /// <summary>The trained model folder this selection actually scores with.</summary>
    [JsonProperty("model_id")]
    public string ModelId { get; set; } = string.Empty;

    /// <summary>Vehicle states the model was trained for (idle, driving, parking).</summary>
    [JsonProperty("states")]
    public List<string> States { get; set; } = new();

    [JsonProperty("has_dbc")]
    public bool HasDbc { get; set; }

    // Date the model's state models were trained (YYYY-MM-DD); empty when unknown.
    [JsonProperty("trained_at")]
    public string TrainedAt { get; set; } = string.Empty;

    /// <summary>
    /// Backend model status (backend/ml/runtime/model_status.py): clean_holdout_evaluated,
    /// clean_unvalidated_no_holdout, clean_held_back, unavailable_no_clean_model, legacy,
    /// general. Empty from a backend that predates it.
    /// </summary>
    [JsonProperty("status")]
    public string Status { get; set; } = string.Empty;

    [JsonProperty("status_reason")]
    public string StatusReason { get; set; } = string.Empty;

    /// <summary>What offline analysis does with this id: clean_2, general or refused.</summary>
    [JsonProperty("offline")]
    public string Offline { get; set; } = string.Empty;

    /// <summary>What live hardware does with this id: clean_2, legacy, general or refused.</summary>
    [JsonProperty("live")]
    public string Live { get; set; } = string.Empty;

    [JsonProperty("model_version")]
    public string ModelVersion { get; set; } = string.Empty;

    public bool IsGeneral => Kind == "general";
    public string ModelLabel => ModelId.ToUpperInvariant();
    public string StatesText => States.Count == 0 ? "--" : string.Join(" · ", States).ToUpperInvariant();

    public string KindText => Status switch
    {
        "clean_holdout_evaluated"      => "CLEAN-2 · HOLDOUT EVALUATED",
        "clean_unvalidated_no_holdout" => "CLEAN-2 NOT PROMOTED · UNVALIDATED",
        "clean_held_back"              => "CLEAN-2 HELD BACK",
        "unavailable_no_clean_model"   => "NO CLEAN MODEL",
        "legacy"                       => "LEGACY MODEL",
        _ => Kind switch
        {
            "general" => "GENERAL MODEL",
            "trained" => "VEHICLE MODEL",
            _         => "DBC PROFILE · GENERAL MODEL",
        },
    };

    /// <summary>
    /// What live hardware will do with this selection: READY (clean-2 or general),
    /// LEGACY, UNAVAILABLE (refused), FALLBACK (a DBC profile scored with the general model).
    /// </summary>
    public string StatusText => Kind == "profile" ? "FALLBACK" : Live switch
    {
        "refused" => "UNAVAILABLE",
        "legacy"  => "LEGACY",
        _         => "READY",
    };

    /// <summary>True when offline analysis would refuse this selection.</summary>
    public bool OfflineRefused => Offline == "refused";

    public string DecodeText => HasDbc ? "DBC DECODE" : "NO DBC";

    // The name is what screen readers and UI Automation report for list items
    // rendered through a DataTemplate.
    public override string ToString() => Name;
}

public sealed class TrainedModelsResponse
{
    [JsonProperty("models")]
    public List<TrainedModelInfo> Models { get; set; } = new();
}
