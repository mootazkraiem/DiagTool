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

public abstract class SectionViewModel : ViewModelBase
{
    private bool isCalibrating = true;
    private string calibrationText = "WAITING FOR SIGNAL...";
    private int calibrationProgress = 0;
    private readonly List<VehicleSnapshot> startupBuffer = new();
    
    public SectionDescriptor? Descriptor { get; }

    protected SectionViewModel(VehicleDataService vehicleDataService, SectionKey key)
    {
        VehicleDataService = vehicleDataService;
        Key = key;
        Descriptor = key == SectionKey.Home ? null : SectionCatalog.For(key);
        vehicleDataService.PropertyChanged += VehicleDataServiceOnPropertyChanged;
        vehicleDataService.DataUpdated += OnDataUpdated;
        
        SaveSnapshotCommand = new RelayCommand(SaveSnapshot);

        NextCardCommand = new RelayCommand(() => { if (CurrentCardIndex < MaxCards - 1) CurrentCardIndex++; });
        PreviousCardCommand = new RelayCommand(() => { if (CurrentCardIndex > 0) CurrentCardIndex--; });
        GoToCardCommand = new RelayCommand<int>(idx => { if (idx >= 0 && idx < MaxCards) CurrentCardIndex = idx; });
    }

    protected VehicleDataService VehicleDataService { get; }

    public SectionKey Key { get; }

    public IRelayCommand SaveSnapshotCommand { get; }

    public bool IsCalibrating
    {
        get => isCalibrating;
        protected set => SetProperty(ref isCalibrating, value);
    }

    public string CalibrationText
    {
        get => calibrationText;
        protected set => SetProperty(ref calibrationText, value);
    }

    public VehicleSnapshot Snapshot => VehicleDataService.CurrentSnapshot ?? VehicleSnapshot.Default();

    // A loaded capture is on screen rather than a live stream.
    protected bool ShowsCapture => string.Equals(Snapshot.Source, "log-playback", StringComparison.OrdinalIgnoreCase)
                                   || VehicleDataService.TotalReplayFrames > 0;

    // Highest score among the frames the analysis flagged (0 when none). Replayed frames
    // carry no score of their own and the fusion score only moves in a live session, so
    // this is the score behind the state shown for a capture.
    protected double PeakFlaggedScore => VehicleDataService.AlertHistory.Count > 0
        ? VehicleDataService.AlertHistory.Max(a => a.Score)
        : 0.0;

    // Navigation and Cards
    private int currentCardIndex = 0;
    public int CurrentCardIndex
    {
        get => currentCardIndex;
        set
        {
            if (SetProperty(ref currentCardIndex, value))
            {
                OnPropertyChanged(nameof(VerticalOffset));
            }
        }
    }

    public virtual int MaxCards => 1;
    public double VerticalOffset => CurrentCardIndex * -800; // Simulated viewport height

    public IRelayCommand NextCardCommand { get; }
    public IRelayCommand PreviousCardCommand { get; }
    public IRelayCommand<int> GoToCardCommand { get; }

    // Derived properties reflect "Calibrating" state
    public double SOC => IsCalibrating ? 0 : Snapshot.SOC;
    public string SOCText => IsCalibrating ? "---" : $"{Snapshot.SOC:F1}%";
    public double SOCRatio => IsCalibrating ? 0 : Clamp(Snapshot.SOC / 100.0, 0.0, 1.0);

    public double BatteryTemp => IsCalibrating ? 0 : Snapshot.BatteryTemp;
    public string BatteryTempText => IsCalibrating ? "---" : $"{BatteryTemp:F1} C";
    public double BatteryTempRatio => IsCalibrating ? 0 : Clamp(BatteryTemp / 120.0, 0.0, 1.0);

    public double BatteryVoltage => IsCalibrating ? 0 : Snapshot.BatteryVoltage;
    public string BatteryVoltageText => IsCalibrating ? "---" : $"{BatteryVoltage:F1} V";

    public double VehicleSpeed => IsCalibrating ? 0 : Snapshot.VehicleSpeed;
    public string VehicleSpeedText => IsCalibrating ? "---" : $"{VehicleSpeed:F1} km/h";

    public double MotorTemp => IsCalibrating ? 0 : Snapshot.MotorTemp;
    public string MotorTempText => IsCalibrating ? "---" : $"{MotorTemp:F1} C";
    public string UnitNameText =>
        Snapshot.Source == "log-playback" ? "LOG ANALYSIS MODE" :
        VehicleDataService.IsRunning ? "CANvision IDS LIVE" :
        "CANvision IDS OFFLINE";

    public string ModelText => "CANvision IDS";
    public string WorkspaceText => string.IsNullOrEmpty(VehicleDataService.ReplayName) || VehicleDataService.ReplayName == "NO REPLAY"
        ? "NO DATASET"
        : VehicleDataService.ReplayName;
    public string SignalHealthText => string.Equals(Snapshot.MotorStatus, "OK", StringComparison.OrdinalIgnoreCase) ? "STABLE" : "DEGRADED";
    public string GpsStatusText => string.Equals(Snapshot.Source, "python-api", StringComparison.OrdinalIgnoreCase) ? "API LINK" : "OFFLINE";
    public string ThermalCoreStateText => BatteryTempText;

    // Compatibility properties (legacy mappings)
    public int Battery => (int)Math.Round(SOC);
    public string BatteryText => $"{Battery}%";
    public double BatteryRatio => SOCRatio;
    public int Temperature => (int)Math.Round(BatteryTemp);
    public string TemperatureText => BatteryTempText;
    public double TemperatureRatio => BatteryTempRatio;

    public double Voltage => BatteryVoltage;
    public string VoltageText => BatteryVoltageText;

    public double SpeedKph => VehicleSpeed;
    public string SpeedText => VehicleSpeedText;

    public string AmpText => IsCalibrating ? "---" : Snapshot.PeakAmperage > 0 ? $"{Snapshot.PeakAmperage:F1} A" : "---";

    public virtual double ReliabilityScore => Snapshot.PerformanceScore;
    public virtual string ReliabilityScoreText =>
        IsCalibrating || Snapshot.PerformanceScore <= 0 ? "---" : $"{Snapshot.PerformanceScore:F1}%";

    public string SessionTimerText =>
        VehicleDataService.LoadedReplayPackets is { Count: >= 2 } packets
            ? TimeSpan.FromSeconds(
                packets[Math.Max(0, Math.Min(VehicleDataService.ProcessedReplayFrames, packets.Count - 1))].Frame.RelativeTimestampSeconds
              ).ToString(@"mm\:ss")
            : "--:--";

    public string TemperatureBand =>
        BatteryTemp switch
        {
            >= 85 => "CRITICAL",
            >= 65 => "ELEVATED",
            >= 45 => "ACTIVE",
            _ => "NOMINAL",
        };

    public string SourceText => NormalizeToken(Snapshot.Source);
    public string UpdatedText => Snapshot.UpdatedAt.ToLocalTime().ToString("HH:mm:ss");
    public string AgeText => BuildAgeText(Snapshot.UpdatedAt);

    public string ConnectivityText =>
        Snapshot.Source?.ToLowerInvariant() switch
        {
            "python-api" => "LIVE FASTAPI",
            "log-playback" => "REPLAY STREAM",
            _ => "OFFLINE",
        };

    public string ThermalMarginText =>
        BatteryTemp >= 85
            ? "THERMAL LIMIT EXCEEDED"
            : $"{Math.Max(0, 85 - BatteryTemp):F1} C TO THERMAL LIMIT";

    public string BatteryReserveText => $"{Math.Max(0, SOC - 20):F1}% ABOVE LOW POWER FLOOR";

    public string SectionEyebrow => Key == SectionKey.Home ? "GARAGE COMMAND DECK" : "TACTICAL VEHICLE BRIEF";
    public string SectionTitle => Key == SectionKey.Home ? "" : SelectorOrDefault(Descriptor?.Title, "SECTION_UNKNOWN");
    public virtual string SectionDescription =>
        Key == SectionKey.Home
            ? "Access the unified vehicle diagnostics console and transition between live systems from a single premium command station."
            : SelectorOrDefault(Descriptor?.BriefingDescription, "SYSTEM_READY");

    public string SectionSignalLine =>
        Key switch
        {
            SectionKey.Home => $"{ConnectivityText} | BATTERY {SOCText} | CORE {BatteryTempText}",
            _ => $"{ConnectivityText} | SOURCE {SourceText} | LAST SYNC {UpdatedText}",
        };

    private string SelectorOrDefault(string? value, string fallback) => string.IsNullOrWhiteSpace(value) ? fallback : value!;

    protected virtual void OnDataUpdated(VehicleSnapshot snapshot)
    {
        if (isCalibrating)
        {
            startupBuffer.Add(snapshot);
            calibrationProgress = startupBuffer.Count;
            CalibrationText = $"CALIBRATING SYSTEM... {calibrationProgress}/4";
            
            if (startupBuffer.Count >= 4)
            {
                IsCalibrating = false;
                CalibrationText = "CALIBRATION COMPLETE";
            }
            else
            {
                OnPropertyChanged(nameof(CalibrationText));
                return;
            }
        }

        OnPropertyChanged(nameof(Snapshot));
        OnPropertyChanged(nameof(IsCalibrating));
        OnPropertyChanged(nameof(CalibrationText));
        OnPropertyChanged(nameof(SOC));
        OnPropertyChanged(nameof(SOCText));
        OnPropertyChanged(nameof(SOCRatio));
        OnPropertyChanged(nameof(BatteryTemp));
        OnPropertyChanged(nameof(BatteryTempText));
        OnPropertyChanged(nameof(BatteryTempRatio));
        OnPropertyChanged(nameof(BatteryVoltage));
        OnPropertyChanged(nameof(BatteryVoltageText));
        OnPropertyChanged(nameof(VehicleSpeed));
        OnPropertyChanged(nameof(VehicleSpeedText));
        OnPropertyChanged(nameof(MotorTemp));
        OnPropertyChanged(nameof(MotorTempText));
        
        OnPropertyChanged(nameof(Battery));
        OnPropertyChanged(nameof(BatteryText));
        OnPropertyChanged(nameof(BatteryRatio));
        OnPropertyChanged(nameof(Temperature));
        OnPropertyChanged(nameof(TemperatureText));
        OnPropertyChanged(nameof(TemperatureBand));
        OnPropertyChanged(nameof(SourceText));
        OnPropertyChanged(nameof(UpdatedText));
        OnPropertyChanged(nameof(AgeText));
        OnPropertyChanged(nameof(ConnectivityText));
        OnPropertyChanged(nameof(ThermalMarginText));
        OnPropertyChanged(nameof(BatteryReserveText));
        OnPropertyChanged(nameof(SectionSignalLine));
    }

    private void SaveSnapshot()
    {
        var dialog = new SaveFileDialog
        {
            Filter = "JSON Data (*.json)|*.json|Text File (*.txt)|*.txt",
            FileName = $"Snapshot_{DateTime.Now:yyyyMMdd_HHmm}",
            Title = "Save Diagnostic Snapshot"
        };

        if (dialog.ShowDialog() == true)
        {
            var json = JsonConvert.SerializeObject(Snapshot, Formatting.Indented);
            System.IO.File.WriteAllText(dialog.FileName, json);
        }
    }

    private void VehicleDataServiceOnPropertyChanged(object? sender, PropertyChangedEventArgs e)
    {
        if (e.PropertyName == nameof(VehicleDataService.CurrentSnapshot))
        {
            RaiseSnapshotChanged();
        }

        if (e.PropertyName == nameof(VehicleDataService.IsRunning))
        {
            OnVehicleDataServiceStateChanged();
        }
    }

    protected virtual void OnVehicleDataServiceStateChanged()
    {
    }

    protected void RaiseSnapshotChanged()
    {
        OnPropertyChanged(nameof(Snapshot));
        OnPropertyChanged(nameof(Battery));
        OnPropertyChanged(nameof(BatteryText));
        OnPropertyChanged(nameof(BatteryRatio));
        OnPropertyChanged(nameof(Temperature));
        OnPropertyChanged(nameof(TemperatureText));
        OnPropertyChanged(nameof(TemperatureRatio));
        OnPropertyChanged(nameof(TemperatureBand));
        OnPropertyChanged(nameof(SourceText));
        OnPropertyChanged(nameof(UpdatedText));
        OnPropertyChanged(nameof(AgeText));
        OnPropertyChanged(nameof(ConnectivityText));
        OnPropertyChanged(nameof(ThermalMarginText));
        OnPropertyChanged(nameof(BatteryReserveText));
        OnPropertyChanged(nameof(Voltage));
        OnPropertyChanged(nameof(VoltageText));
        OnPropertyChanged(nameof(SpeedKph));
        OnPropertyChanged(nameof(SpeedText));
        OnPropertyChanged(nameof(GpsStatusText));
        OnPropertyChanged(nameof(SessionTimerText));
        OnPropertyChanged(nameof(SectionSignalLine));
        OnPropertyChanged(nameof(AmpText));
        OnPropertyChanged(nameof(ModelText));
        OnPropertyChanged(nameof(WorkspaceText));
        OnPropertyChanged(nameof(SignalHealthText));
        OnPropertyChanged(nameof(ThermalCoreStateText));
        OnPropertyChanged(nameof(UnitNameText));
        OnDataUpdated(Snapshot);
    }

    protected static double Clamp(double value, double min, double max)
    {
        if (value < min)
        {
            return min;
        }

        if (value > max)
        {
            return max;
        }

        return value;
    }

    private static string NormalizeToken(string? value)
    {
        var normalized = value ?? string.Empty;
        return string.IsNullOrWhiteSpace(normalized)
            ? "UNKNOWN"
            : normalized.Replace('_', ' ').Replace('-', ' ').ToUpperInvariant();
    }

    private static string BuildAgeText(DateTime updatedAt)
    {
        var age = DateTime.UtcNow - updatedAt.ToUniversalTime();
        if (age.TotalSeconds < 5)
        {
            return "JUST NOW";
        }

        if (age.TotalMinutes < 1)
        {
            return $"{(int)Math.Max(1, age.TotalSeconds)}S AGO";
        }

        if (age.TotalHours < 1)
        {
            return $"{(int)age.TotalMinutes}M AGO";
        }

        return $"{(int)age.TotalHours}H AGO";
    }
}

