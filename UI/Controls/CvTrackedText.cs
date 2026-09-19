using System.Linq;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Documents;
using System.Windows.Media;

namespace CANvision.Native.UI.Controls;

/// <summary>
/// TextBlock with letter-spacing ("tracking") and optional upper-casing.
///
/// WPF TextBlock has no CSS letter-spacing / text-transform equivalent, yet the
/// CANvision reference sets almost every micro-label in widely tracked
/// uppercase ("F U S I O N  S C O R E"). This control rebuilds its Text from
/// <see cref="Label"/> with hair spaces (U+200A) between glyphs, which gives the
/// same optical tracking without per-glyph layout code.
///
/// Set <see cref="Label"/> (literal or binding) instead of Text.
/// </summary>
public class CvTrackedText : TextBlock
{
    private const char HairSpace = ' ';

    public static readonly DependencyProperty LabelProperty = DependencyProperty.Register(
        nameof(Label), typeof(string), typeof(CvTrackedText),
        new PropertyMetadata(null, OnShapeChanged));

    /// <summary>Hair spaces inserted between glyphs. 0 disables tracking.</summary>
    public static readonly DependencyProperty TrackingProperty = DependencyProperty.Register(
        nameof(Tracking), typeof(int), typeof(CvTrackedText),
        new PropertyMetadata(1, OnShapeChanged));

    public static readonly DependencyProperty UpperProperty = DependencyProperty.Register(
        nameof(Upper), typeof(bool), typeof(CvTrackedText),
        new PropertyMetadata(true, OnShapeChanged));

    public string? Label
    {
        get => (string?)GetValue(LabelProperty);
        set => SetValue(LabelProperty, value);
    }

    public int Tracking
    {
        get => (int)GetValue(TrackingProperty);
        set => SetValue(TrackingProperty, value);
    }

    public bool Upper
    {
        get => (bool)GetValue(UpperProperty);
        set => SetValue(UpperProperty, value);
    }

    private static void OnShapeChanged(DependencyObject d, DependencyPropertyChangedEventArgs e)
        => ((CvTrackedText)d).Rebuild();

    // Gaps are always set in a proportional face. In a monospace face (JetBrains
    // Mono) every glyph, hair space included, takes a full cell, which would
    // double the width instead of adding a hairline of tracking.
    private static readonly FontFamily GapFont = new("Segoe UI");

    private void Rebuild()
    {
        var source = Label ?? string.Empty;
        if (Upper)
        {
            source = source.ToUpperInvariant();
        }

        Inlines.Clear();
        if (Tracking <= 0 || source.Length < 2)
        {
            Inlines.Add(new Run(source));
            return;
        }

        var gap = new string(HairSpace, Tracking);
        for (var i = 0; i < source.Length; i++)
        {
            Inlines.Add(new Run(source[i].ToString()));
            if (i < source.Length - 1)
            {
                Inlines.Add(new Run(gap) { FontFamily = GapFont });
            }
        }
    }
}
