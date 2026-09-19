using System.Collections.Generic;
using System.ComponentModel;
using System.Collections.ObjectModel;
using System.Linq;
using System.IO;
using CommunityToolkit.Mvvm.Input;
using CommunityToolkit.Mvvm.ComponentModel;
using CANvision.Native.Models;
using CANvision.Native.Services;
using System.Windows.Threading;
using System.Threading.Tasks;
using Newtonsoft.Json;
using Microsoft.Win32;

namespace CANvision.Native.ViewModels;

public sealed class SettingsViewModel : SectionViewModel
{
    private readonly PythonApiClient pythonApiClient;
    private readonly CANvision.Native.Models.AppConfig appConfig;
    private string detectionModelText  = "IsolationForest + KMeans";
    private string modelClustersText   = "--";
    private string llmProviderText     = "--";
    private string modelStatusText     = "CHECKING...";
    private string saveStatusText      = string.Empty;
    private string hwStatusText        = "DISCONNECTED";
    private string hwChannel           = "0";
    private string hwBitrate           = "500000";
    private string selectedHwInterface = "virtual";
    private string pythonCanWarning    = "Checking python-can...";
    private bool   pythonCanAvailable  = false;
    private DispatcherTimer? hwPollTimer;

    public SettingsViewModel(VehicleDataService vehicleDataService, PythonApiClient pythonApiClient, ModelSelectionService modelSelection)
        : base(vehicleDataService, SectionKey.Settings)
    {
        this.pythonApiClient = pythonApiClient;
        appConfig = CANvision.Native.Models.AppConfig.Load();
        ModelSelection = modelSelection;
        modelSelection.SelectionChanged += _ =>
        {
            OnPropertyChanged(nameof(SelectedHwVehicleId));
            OnPropertyChanged(nameof(TrainingDateText));
        };
        modelSelection.Models.CollectionChanged += (_, _) => OnPropertyChanged(nameof(TrainingDateText));

        SettingsCategories = new ObservableCollection<string>
        {
            "OBD2 ADAPTER",
            "CAN INTERFACE",
            "VEHICLE PROFILES",
            "THEME",
            "AI MODEL",
            "EXPORT",
        };
        ProfileCards = new ObservableCollection<ProfileItem>
        {
            new("P-800 Performance", "ACTIVE", "High-response track profile"),
            new("Street Touring", "SYNCED", "Balanced drive calibration"),
            new("Thermal Safe", "ARCHIVED", "Cooling-first endurance preset"),
        };
        HardwareInterfaceItems = new ObservableCollection<string>
        {
            "virtual", "pcan", "kvaser", "socketcan", "slcan", "vector", "ixxat",
        };
        HardwareVehicleItems = new ObservableCollection<VehicleProfileItem>();

        SelectSettingsCategoryCommand = new RelayCommand<string>(category => SelectedSettingsCategory = category ?? "OBD2 ADAPTER");
        selectedSettingsCategory = "OBD2 ADAPTER";
        SaveSettingsCommand        = new RelayCommand(SaveSettings);
        RestoreDefaultsCommand     = new RelayCommand(RestoreDefaults);
        LaunchSimulatorCommand     = new AsyncRelayCommand(LaunchSimulatorAsync);
        ConnectHardwareCommand     = new AsyncRelayCommand(ConnectHardwareAsync);
        DisconnectHardwareCommand  = new AsyncRelayCommand(DisconnectHardwareAsync);
        RefreshPortsCommand        = new AsyncRelayCommand(RefreshPortsAsync);

        HardwareChannelItems = new ObservableCollection<string> { "0", "PCAN_USBBUS1", "can0", "/dev/can0", "COM3", "COM4" };

        _ = RefreshModelInfoAsync();
        _ = LoadHardwareVehiclesAsync();
        _ = InitHardwareAsync();
    }

    private string selectedSettingsCategory;

    public ObservableCollection<string>              SettingsCategories     { get; }
    public ObservableCollection<ProfileItem>         ProfileCards           { get; }
    public ObservableCollection<string>              HardwareInterfaceItems { get; }
    public ObservableCollection<VehicleProfileItem>  HardwareVehicleItems   { get; }
    public ObservableCollection<string>              HardwareChannelItems   { get; }
    public IRelayCommand<string>  SelectSettingsCategoryCommand { get; }
    public IRelayCommand          SaveSettingsCommand           { get; }
    public IRelayCommand          RestoreDefaultsCommand        { get; }
    public IAsyncRelayCommand     LaunchSimulatorCommand        { get; }
    public IAsyncRelayCommand     ConnectHardwareCommand        { get; }
    public IAsyncRelayCommand     DisconnectHardwareCommand     { get; }
    public IAsyncRelayCommand     RefreshPortsCommand           { get; }

    public bool PythonCanAvailable
    {
        get => pythonCanAvailable;
        private set => SetProperty(ref pythonCanAvailable, value);
    }

    public string PythonCanWarning
    {
        get => pythonCanWarning;
        private set => SetProperty(ref pythonCanWarning, value);
    }

    public string SelectedSettingsCategory
    {
        get => selectedSettingsCategory;
        set => SetProperty(ref selectedSettingsCategory, value);
    }

    // ── Hardware connect props ─────────────────────────────────────────────────

    public string SelectedHwInterface
    {
        get => selectedHwInterface;
        set => SetProperty(ref selectedHwInterface, value ?? "virtual");
    }

    /// <summary>The shared vehicle / AI model selection. Hardware connect sends it as the
    /// vehicle id, which the backend uses for the live model and for DBC decode.</summary>
    public ModelSelectionService ModelSelection { get; }

    public string SelectedHwVehicleId
    {
        get => ModelSelection.SelectedModelId;
        set => ModelSelection.Select(value);
    }

    public string HwChannel
    {
        get => hwChannel;
        // Ignore null: a list selector reports null while SCAN rebuilds its items,
        // and mapping that to "0" silently replaced the channel the user had typed.
        set { if (value is not null) SetProperty(ref hwChannel, value); }
    }

    public string HwBitrate
    {
        get => hwBitrate;
        set => SetProperty(ref hwBitrate, value ?? "500000");
    }

    public string HwStatusText
    {
        get => hwStatusText;
        private set => SetProperty(ref hwStatusText, value);
    }

    // ── Config-backed settings ─────────────────────────────────────────────────

    public string GoogleApiKey
    {
        get => appConfig.GoogleApiKey;
        set { appConfig.GoogleApiKey = value ?? string.Empty; OnPropertyChanged(); }
    }

    public double AlertThreshold
    {
        get => appConfig.AlertThreshold;
        set
        {
            appConfig.AlertThreshold = Math.Max(0.1, Math.Min(1.0, Math.Round(value, 2)));
            OnPropertyChanged();
            OnPropertyChanged(nameof(AlertThresholdText));
        }
    }

    public string AlertThresholdText => $"{AlertThreshold:F2}";

    // Legacy OBD2 fields kept for XAML binding compatibility
    public string AdapterName   { get; set; } = "ELM327 USB";
    public string BaudRateText  { get; set; } = "500000";
    public string PortName      { get; set; } = "COM3";

    // ── Read-only display ──────────────────────────────────────────────────────

    public string RuntimeMode         => ConnectivityText;
    public string ApiEndpoint         => VehicleDataService.ApiEndpoint;
    public string JsonFallbackPath    => VehicleDataService.JsonFallbackPath;
    public string RefreshIntervalText => $"{(int)VehicleDataService.RefreshInterval.TotalMilliseconds} MS";
    public string LatencyText         => $"{VehicleDataService.RuntimeLatencyMs:F1} ms";

    public string DetectionModelText { get => detectionModelText; private set => SetProperty(ref detectionModelText, value); }
    public string ModelClustersText  { get => modelClustersText;  private set => SetProperty(ref modelClustersText,  value); }
    public string LlmProviderText    { get => llmProviderText;    private set => SetProperty(ref llmProviderText,    value); }
    public string ModelStatusText    { get => modelStatusText;    private set => SetProperty(ref modelStatusText,    value); }
    public string SaveStatusText     { get => saveStatusText;     private set => SetProperty(ref saveStatusText,     value); }

    // Training date of the selected model, from /api/models.
    public string TrainingDateText => string.IsNullOrWhiteSpace(ModelSelection.SelectedModel?.TrainedAt)
        ? "N/A"
        : ModelSelection.SelectedModel!.TrainedAt;

    // ── Commands ───────────────────────────────────────────────────────────────

    private void SaveSettings()
    {
        appConfig.Save();
        if (!string.IsNullOrWhiteSpace(appConfig.GoogleApiKey))
            Environment.SetEnvironmentVariable("GOOGLE_API_KEY", appConfig.GoogleApiKey);
        SaveStatusText = "SETTINGS SAVED";
        _ = ClearSaveStatusAfterDelay();
    }

    private void RestoreDefaults()
    {
        AlertThreshold = 0.55;
        GoogleApiKey   = string.Empty;
        SaveStatusText = "DEFAULTS RESTORED";
        _ = ClearSaveStatusAfterDelay();
    }

    private async Task LaunchSimulatorAsync()
    {
        SaveStatusText = "STARTING ATTACK SIMULATION...";
        await VehicleDataService.StartSimulatorAsync().ConfigureAwait(true);
        SaveStatusText = "ATTACK SIMULATION ACTIVE — GO TO TELEMETRY";
    }

    private async Task ClearSaveStatusAfterDelay()
    {
        await Task.Delay(3000).ConfigureAwait(true);
        SaveStatusText = string.Empty;
    }

    private async Task LoadHardwareVehiclesAsync()
    {
        for (int attempt = 0; attempt < 15; attempt++)
        {
            if (attempt > 0)
                await Task.Delay(2000).ConfigureAwait(true);
            try
            {
                var result = await VehicleDataService.GetVehicleListAsync().ConfigureAwait(true);
                if (result is null) continue;
                HardwareVehicleItems.Clear();
                foreach (var v in result.Vehicles)
                    HardwareVehicleItems.Add(v);
                if (HardwareVehicleItems.Count > 0 && string.IsNullOrEmpty(SelectedHwVehicleId))
                    SelectedHwVehicleId = HardwareVehicleItems[0].Id;
                return;
            }
            catch { /* backend may be starting */ }
        }
    }

    private async Task ConnectHardwareAsync()
    {
        HwStatusText = "CONNECTING...";
        if (!int.TryParse(HwBitrate, out var bitrate)) bitrate = 500_000;
        var ok = await VehicleDataService.ConnectHardwareAsync(
            SelectedHwInterface, HwChannel, bitrate, SelectedHwVehicleId).ConfigureAwait(true);
        if (ok)
        {
            HwStatusText = $"CONNECTED — {SelectedHwInterface.ToUpperInvariant()}";
            hwPollTimer = new DispatcherTimer { Interval = TimeSpan.FromSeconds(2) };
            hwPollTimer.Tick += async (_, _) => await PollHardwareStatusAsync().ConfigureAwait(true);
            hwPollTimer.Start();
        }
        else
        {
            HwStatusText = "CONNECTION FAILED — check interface and channel";
        }
    }

    private async Task DisconnectHardwareAsync()
    {
        hwPollTimer?.Stop();
        hwPollTimer = null;
        HwStatusText = "DISCONNECTING...";
        await VehicleDataService.DisconnectHardwareAsync().ConfigureAwait(true);
        HwStatusText = "DISCONNECTED";
    }

    private async Task PollHardwareStatusAsync()
    {
        try
        {
            var s = await VehicleDataService.GetHardwareStatusAsync().ConfigureAwait(true);
            if (s is null) return;
            if (!s.IsConnected)
            {
                hwPollTimer?.Stop();
                hwPollTimer = null;
                HwStatusText = "DISCONNECTED (lost connection)";
                return;
            }
            HwStatusText = $"LIVE · {s.InterfaceType.ToUpperInvariant()} · {s.FramesReceived:N0} frames · score {s.CurrentScore:F3}";
        }
        catch { /* non-fatal */ }
    }

    private async Task InitHardwareAsync()
    {
        for (int attempt = 0; attempt < 15; attempt++)
        {
            if (attempt > 0)
                await Task.Delay(2000).ConfigureAwait(true);
            try
            {
                var check = await VehicleDataService.GetHardwareCheckAsync().ConfigureAwait(true);
                if (check is null) continue;
                PythonCanAvailable = check.PythonCanAvailable;
                PythonCanWarning = check.PythonCanAvailable
                    ? $"python-can {check.PythonCanVersion} · pyserial {(check.PyserialAvailable ? "OK" : "missing")}"
                    : "python-can NOT installed — run: pip install python-can pyserial";
                await RefreshPortsAsync().ConfigureAwait(true);
                return;
            }
            catch { /* backend may still be starting */ }
        }
    }

    private async Task RefreshPortsAsync()
    {
        try
        {
            var result = await VehicleDataService.GetHardwarePortsAsync().ConfigureAwait(true);
            if (result is null) return;
            HardwareChannelItems.Clear();
            foreach (var p in result.Ports)
                HardwareChannelItems.Add(p.Name);
            // Always keep useful defaults at the end
            foreach (var def in new[] { "0", "PCAN_USBBUS1", "can0", "/dev/can0" })
                if (!HardwareChannelItems.Contains(def)) HardwareChannelItems.Add(def);
            if (HardwareChannelItems.Count > 0 && string.IsNullOrEmpty(HwChannel))
                HwChannel = HardwareChannelItems[0];
        }
        catch { /* non-fatal */ }
    }

    private async Task RefreshModelInfoAsync()
    {
        for (int attempt = 0; attempt < 15; attempt++)
        {
            if (attempt > 0)
                await Task.Delay(2000).ConfigureAwait(true);
            try
            {
                var health = await pythonApiClient.GetSystemHealthDetailAsync(CancellationToken.None).ConfigureAwait(true);
                if (health is null) { ModelStatusText = "BACKEND OFFLINE"; continue; }
                DetectionModelText = health.ModelLoaded ? "IsolationForest + KMeans" : "MODEL NOT LOADED";
                ModelClustersText  = health.ModelLoaded ? $"{health.ModelClusters} clusters" : "--";
                LlmProviderText    = string.IsNullOrWhiteSpace(health.LlmProvider) ? "NONE" : health.LlmProvider.ToUpperInvariant();
                ModelStatusText    = health.ModelLoaded ? "ACTIVE" : "OFFLINE";
                return;
            }
            catch { ModelStatusText = "BACKEND OFFLINE"; }
        }
    }

    protected override void OnDataUpdated(VehicleSnapshot snapshot)
    {
        OnPropertyChanged(nameof(RuntimeMode));
        OnPropertyChanged(nameof(LatencyText));
    }
}

