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

    public bool IsGeneral => Kind == "general";
    public string ModelLabel => ModelId.ToUpperInvariant();
    public string StatesText => States.Count == 0 ? "--" : string.Join(" · ", States).ToUpperInvariant();

    public string KindText => Kind switch
    {
        "general" => "GENERAL MODEL",
        "trained" => "VEHICLE MODEL",
        _         => "DBC PROFILE · GENERAL MODEL",
    };

    /// <summary>READY for a real trained model; FALLBACK when the selection scores with the general model.</summary>
    public string StatusText => Kind == "profile" ? "FALLBACK" : "READY";

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
