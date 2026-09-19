using System;
using System.IO;
using Newtonsoft.Json;

namespace CANvision.Native.Models;

public sealed class AppConfig
{
    private static readonly string ConfigPath = Path.Combine(
        Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData),
        "CANvision", "config.json");

    private static readonly object SharedLock = new();
    private static AppConfig? shared;

    [JsonProperty("google_api_key")]
    public string GoogleApiKey { get; set; } = string.Empty;

    [JsonProperty("alert_threshold")]
    public double AlertThreshold { get; set; } = 0.55;

    /// <summary>
    /// The selected vehicle / AI model id ("general" or a trained model id).
    /// Owned by <see cref="Services.ModelSelectionService"/>; stored here so it
    /// persists through the same config file as every other setting.
    /// </summary>
    [JsonProperty("selected_model_id")]
    public string SelectedModelId { get; set; } = "general";

    /// <summary>"dark" (default) or "light"; applied by <see cref="Services.ThemeService"/>.</summary>
    [JsonProperty("theme")]
    public string Theme { get; set; } = "dark";

    /// <summary>
    /// The process-wide configuration, read from disk on first use. Every caller
    /// shares this one instance, so a Save() from one screen can never write back
    /// another screen's setting with a stale value.
    /// </summary>
    public static AppConfig Load()
    {
        lock (SharedLock)
        {
            return shared ??= LoadFromDisk();
        }
    }

    private static AppConfig LoadFromDisk()
    {
        try
        {
            if (File.Exists(ConfigPath))
            {
                var json = File.ReadAllText(ConfigPath);
                return JsonConvert.DeserializeObject<AppConfig>(json) ?? new AppConfig();
            }
        }
        catch { }
        return new AppConfig();
    }

    public void Save()
    {
        try
        {
            var dir = Path.GetDirectoryName(ConfigPath);
            if (!string.IsNullOrEmpty(dir))
                Directory.CreateDirectory(dir);
            File.WriteAllText(ConfigPath, JsonConvert.SerializeObject(this, Formatting.Indented));
        }
        catch { }
    }
}
