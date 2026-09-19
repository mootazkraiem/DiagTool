using System;
using System.Linq;
using System.Windows;
using CANvision.Native.Models;

namespace CANvision.Native.Services;

/// <summary>
/// Switches the app between the dark and light palettes.
///
/// Every palette colour is referenced with DynamicResource, so replacing the palette
/// dictionary (UI/Theme/Palette.Dark.xaml or Palette.Light.xaml) restyles the running
/// app in place. The choice persists in <see cref="AppConfig.Theme"/>.
/// </summary>
public static class ThemeService
{
    public const string Dark = "dark";
    public const string Light = "light";

    public static string Current { get; private set; } = Dark;

    public static bool IsLight => Current == Light;

    public static event Action<string>? Changed;

    /// <summary>Load the palette for <paramref name="theme"/>; anything but "light" means dark.</summary>
    public static void Apply(string? theme)
    {
        var target = string.Equals(theme, Light, StringComparison.OrdinalIgnoreCase) ? Light : Dark;
        var merged = Application.Current.Resources.MergedDictionaries;
        var palette = new ResourceDictionary
        {
            Source = new Uri($"UI/Theme/Palette.{(target == Light ? "Light" : "Dark")}.xaml", UriKind.Relative),
        };

        // Replace in place: the palette must stay ahead of the dictionaries that use it.
        var existing = merged.FirstOrDefault(d => d.Source?.OriginalString.Contains("Palette.") == true);
        if (existing is null)
            merged.Insert(0, palette);
        else
            merged[merged.IndexOf(existing)] = palette;

        Current = target;
        Changed?.Invoke(target);
    }

    /// <summary>Switch to the other palette and save the choice.</summary>
    public static void Toggle()
    {
        Apply(IsLight ? Dark : Light);
        var config = AppConfig.Load();
        config.Theme = Current;
        config.Save();
    }
}
