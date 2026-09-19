using System;
using System.Collections.Generic;
using System.Collections.ObjectModel;
using System.Linq;
using System.Threading;
using System.Threading.Tasks;
using CANvision.Native.Models;
using CommunityToolkit.Mvvm.ComponentModel;

namespace CANvision.Native.Services;

/// <summary>
/// The one source of truth for the selected vehicle / AI model.
///
/// Offline import, Log Playback, Settings and Hardware Setup all read and write the
/// selection here; it persists in <see cref="AppConfig.SelectedModelId"/>. The list
/// of models comes from the backend's <c>GET /api/models</c>, which reports exactly
/// the trained bundles the runtime can load (plus DBC profiles that fall back to the
/// general model). GENERAL MODEL is always present, even before the backend answers.
/// </summary>
public sealed class ModelSelectionService : ObservableObject
{
    public const string GeneralId = "general";

    private readonly PythonApiClient pythonApiClient;
    private readonly AppLogger logger;
    private readonly AppConfig config;
    private string selectedModelId;
    private bool isLoaded;

    public ModelSelectionService(PythonApiClient pythonApiClient, AppLogger logger)
    {
        this.pythonApiClient = pythonApiClient;
        this.logger = logger;
        config = AppConfig.Load();
        selectedModelId = string.IsNullOrWhiteSpace(config.SelectedModelId) ? GeneralId : config.SelectedModelId.Trim();
        Models = new ObservableCollection<TrainedModelInfo> { GeneralPlaceholder() };
    }

    public ObservableCollection<TrainedModelInfo> Models { get; }

    public bool IsLoaded
    {
        get => isLoaded;
        private set => SetProperty(ref isLoaded, value);
    }

    public int TrainedModelCount => Models.Count(m => m.Kind == "trained");

    /// <summary>The selected id. Bound TwoWay by the selectors; null/empty writes are ignored
    /// (a ComboBox briefly reports null while its list is being refreshed).</summary>
    public string SelectedModelId
    {
        get => selectedModelId;
        set => Select(value);
    }

    /// <summary>
    /// The selected model object, for selectors that bind SelectedItem. After the list is
    /// reloaded this returns a new instance, which is what makes a selector that lost its
    /// selection during the reload pick it up again - re-announcing an unchanged id did not.
    /// Null writes are ignored, as for <see cref="SelectedModelId"/>.
    /// </summary>
    public TrainedModelInfo SelectedModel
    {
        get => Models.FirstOrDefault(m => m.Id == selectedModelId) ?? Models.First(m => m.Id == GeneralId);
        set => Select(value?.Id);
    }

    public event Action<TrainedModelInfo>? SelectionChanged;

    public void Select(string? id)
    {
        if (string.IsNullOrWhiteSpace(id)) return;
        var normalized = id!.Trim();
        if (string.Equals(normalized, selectedModelId, StringComparison.Ordinal)) return;

        selectedModelId = normalized;
        config.SelectedModelId = normalized;
        config.Save();
        logger.Info($"[MODEL] Selected vehicle/AI model: {normalized}");
        RaiseSelection();
    }

    /// <summary>Fetch the model list from the backend, retrying while it starts.</summary>
    public async Task LoadAsync()
    {
        for (var attempt = 0; attempt < 15; attempt++)
        {
            if (attempt > 0)
                await Task.Delay(2000).ConfigureAwait(true);
            try
            {
                var response = await pythonApiClient.GetTrainedModelsAsync(CancellationToken.None).ConfigureAwait(true);
                if (response?.Models is not { Count: > 0 } models) continue;

                Models.Clear();
                if (!models.Any(m => m.Id == GeneralId))
                    Models.Add(GeneralPlaceholder());
                foreach (var model in models)
                    Models.Add(model);
                IsLoaded = true;
                OnPropertyChanged(nameof(TrainedModelCount));

                // A persisted selection whose model no longer exists falls back to GENERAL.
                var resolved = Resolve(selectedModelId, Models.Select(m => m.Id));
                if (resolved != selectedModelId)
                {
                    logger.Info($"[MODEL] Saved model '{selectedModelId}' is not available — using {resolved}.");
                    Select(resolved);
                }
                else
                {
                    RaiseSelection();   // re-sync selectors after the list was rebuilt
                }
                logger.Info($"[MODEL] {Models.Count} selectable models ({TrainedModelCount} vehicle models); selected {selectedModelId}.");
                return;
            }
            catch (Exception exception)
            {
                logger.Error("Loading trained model list failed.", exception);
            }
        }
    }

    /// <summary>The id to use: the requested one when it is available, otherwise GENERAL.</summary>
    public static string Resolve(string? requested, IEnumerable<string> availableIds)
    {
        if (string.IsNullOrWhiteSpace(requested)) return GeneralId;
        var id = requested!.Trim();
        return availableIds.Contains(id, StringComparer.Ordinal) ? id : GeneralId;
    }

    private void RaiseSelection()
    {
        OnPropertyChanged(nameof(SelectedModelId));
        OnPropertyChanged(nameof(SelectedModel));
        SelectionChanged?.Invoke(SelectedModel);
    }

    private static TrainedModelInfo GeneralPlaceholder() => new()
    {
        Id = GeneralId,
        Name = "General Model",
        Kind = "general",
        ModelId = GeneralId,
    };
}
