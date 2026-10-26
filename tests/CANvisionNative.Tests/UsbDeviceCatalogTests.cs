using CANvision.Native.Models;
using CANvision.Native.Services;
using Xunit;

namespace CANvision.Native.Tests;

/// <summary>
/// START LIVE SESSION unlocks only when a USB device is plugged in: Arduino, Raspberry Pi
/// or a USB-serial bridge counts; Bluetooth and built-in COM ports do not.
/// </summary>
public sealed class UsbDeviceCatalogTests
{
    private static HardwarePortInfo Port(string name, string hwid) => new() { Name = name, HwId = hwid };

    [Theory]
    [InlineData("USB VID:PID=2341:0043 SER=75930313234351F0A1B1 LOCATION=1-1:1.0", "Arduino")]
    [InlineData("USB VID:PID=1a86:7523 SER= LOCATION=1-2", "Arduino-compatible (CH340)")]
    [InlineData("USB VID:PID=2E8A:000A SER=E6609103C3432A2F LOCATION=1-3:x.0", "Raspberry Pi (RP2040)")]
    [InlineData("USB VID:PID=0525:A4A7 LOCATION=1-4", "Raspberry Pi (USB gadget)")]
    [InlineData("USB VID:PID=16D0:117E SER=ABC LOCATION=1-5", "CANable (slcan)")]
    [InlineData("USB VID:PID=1234:5678 LOCATION=1-6", "USB serial device (1234:5678)")]
    public void UsbDevices_AreNamed(string hwid, string expected) =>
        Assert.Equal(expected, UsbDeviceCatalog.Describe(Port("COM5", hwid)));

    [Theory]
    [InlineData(@"BTHENUM\{00001101-0000-1000-8000-00805F9B34FB}_LOCALMFG&0000\7&2D2A5A1&0&000000000000_00000000")]
    [InlineData(@"ACPI\PNP0501\1")]
    [InlineData("")]
    public void BluetoothAndBuiltInPorts_AreNotHardware(string hwid) =>
        Assert.Null(UsbDeviceCatalog.Describe(Port("COM3", hwid)));

    [Fact]
    public void FirstDevice_SkipsNonUsbPorts_AndIsNullWhenNothingIsPlugged()
    {
        var bluetooth = Port("COM3", @"BTHENUM\{00001101-0000-1000-8000-00805F9B34FB}_LOCALMFG&0000\7&2D2A5A1");
        Assert.Null(UsbDeviceCatalog.FirstDevice(new[] { bluetooth }));
        Assert.Null(UsbDeviceCatalog.FirstDevice(null));
        Assert.Equal("Arduino · COM7",
            UsbDeviceCatalog.FirstDevice(new[] { bluetooth, Port("COM7", "USB VID:PID=2341:0043 LOCATION=1-1") }));
    }
}
