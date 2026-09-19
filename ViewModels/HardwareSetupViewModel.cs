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

// ──────────────────────────────────────────────────────────────────────────────
// HardwareSetupViewModel — dedicated screen for configuring a live CAN adapter
// ──────────────────────────────────────────────────────────────────────────────
//
// This is a thin wrapper around SettingsViewModel rather than a duplicate of
// its hardware-connect logic: the underlying interface/channel/bitrate state
// and the Connect/Disconnect/Scan commands stay single-sourced on Settings
// (Settings keeps a simplified Connect/Disconnect-only view of the same
// state for quick testing), so both screens read and write the exact same
// live values with no risk of the two drifting out of sync.

public sealed class HardwareSetupViewModel : SectionViewModel
{
    public HardwareSetupViewModel(VehicleDataService vehicleDataService, SettingsViewModel settings)
        : base(vehicleDataService, SectionKey.HardwareSetup)
    {
        Settings = settings;
    }

    public SettingsViewModel Settings { get; }
}

