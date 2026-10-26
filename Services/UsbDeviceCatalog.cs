using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using System.Text.RegularExpressions;
using CANvision.Native.Models;

namespace CANvision.Native.Services;

/// <summary>
/// Names the USB serial devices a live session can use (Arduino, Raspberry Pi, USB-serial
/// CAN bridges) from the hardware id pyserial reports for each COM port
/// (GET /api/live/hardware/ports, e.g. "USB VID:PID=2341:0043 SER=... LOCATION=1-1:1.0").
/// Ports that are not USB devices plugged into the PC - Bluetooth serial links, built-in
/// ACPI/PCI ports - are not hardware for a live session and return null.
/// </summary>
public static class UsbDeviceCatalog
{
    private static readonly Regex VidPid = new(@"VID:PID=([0-9A-Fa-f]{4}):([0-9A-Fa-f]{4})", RegexOptions.Compiled);

    // USB vendor ids (and a few vendor:product pairs where the vendor id alone is shared).
    private static readonly Dictionary<string, string> Known = new()
    {
        ["2341"] = "Arduino",
        ["2A03"] = "Arduino",
        ["1A86"] = "Arduino-compatible (CH340)",
        ["0403"] = "FTDI USB-serial",
        ["10C4"] = "CP210x USB-serial",
        ["2E8A"] = "Raspberry Pi (RP2040)",
        ["0525:A4A7"] = "Raspberry Pi (USB gadget)",
        ["1D6B"] = "Raspberry Pi (USB gadget)",
        ["16D0:117E"] = "CANable (slcan)",
        ["0483:5740"] = "STM32 USB-serial",
    };

    /// <summary>A display name for a USB device on this port, or null when it is not one.</summary>
    public static string? Describe(HardwarePortInfo port)
    {
        var match = VidPid.Match(port.HwId ?? string.Empty);
        if (!match.Success)
            return null;
        var vid = match.Groups[1].Value.ToUpperInvariant();
        var pid = match.Groups[2].Value.ToUpperInvariant();
        if (Known.TryGetValue($"{vid}:{pid}", out var exact)) return exact;
        if (Known.TryGetValue(vid, out var vendor)) return vendor;
        return string.Format(CultureInfo.InvariantCulture, "USB serial device ({0}:{1})", vid, pid);
    }

    /// <summary>The first plugged USB device as "name · COM5", or null when none is plugged in.</summary>
    public static string? FirstDevice(IEnumerable<HardwarePortInfo>? ports) =>
        ports?.Select(p => (Port: p, Name: Describe(p)))
              .Where(x => x.Name is not null)
              .Select(x => $"{x.Name} · {x.Port.Name}")
              .FirstOrDefault();
}
