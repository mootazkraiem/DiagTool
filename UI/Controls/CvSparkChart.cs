using System;
using System.Collections.Generic;
using System.Linq;
using System.Windows;
using System.Windows.Controls;
using LiveChartsCore;
using LiveChartsCore.Measure;
using LiveChartsCore.SkiaSharpView;
using LiveChartsCore.SkiaSharpView.Painting;
using LiveChartsCore.SkiaSharpView.WPF;
using CANvision.Native.Services;
using SkiaSharp;

namespace CANvision.Native.UI.Controls;

/// <summary>
/// Compact CANvision trend chart: a single LiveCharts2 line with an optional
/// gradient area, no axes, no legend, no tooltip. Used for telemetry channel
/// traces and metric-tile sparklines.
///
/// Bind <see cref="Values"/> to a numeric history snapshot (a fresh sequence per
/// update). The chart only draws what it is given; with fewer than two points
/// it shows nothing rather than inventing a line.
/// </summary>
public sealed class CvSparkChart : ContentControl
{
    public static readonly DependencyProperty ValuesProperty = DependencyProperty.Register(
        nameof(Values), typeof(IEnumerable<double>), typeof(CvSparkChart),
        new PropertyMetadata(null, (d, _) => ((CvSparkChart)d).ApplyValues()));

    /// <summary>Line colour as a hex string (#RRGGBB), matching the palette tokens.</summary>
    public static readonly DependencyProperty StrokeHexProperty = DependencyProperty.Register(
        nameof(StrokeHex), typeof(string), typeof(CvSparkChart),
        new PropertyMetadata("#2FF0D6", (d, _) => ((CvSparkChart)d).ApplyPaint()));

    public static readonly DependencyProperty ShowAreaProperty = DependencyProperty.Register(
        nameof(ShowArea), typeof(bool), typeof(CvSparkChart),
        new PropertyMetadata(true, (d, _) => ((CvSparkChart)d).ApplyPaint()));

    public static readonly DependencyProperty LineThicknessProperty = DependencyProperty.Register(
        nameof(LineThickness), typeof(double), typeof(CvSparkChart),
        new PropertyMetadata(1.4, (d, _) => ((CvSparkChart)d).ApplyPaint()));

    /// <summary>
    /// Fixes the top of the value axis, so a trace can be read against a fixed
    /// scale (and an overlaid threshold line lands in the right place). Leave as
    /// NaN - the default - to keep the axis auto-scaling to the data.
    /// </summary>
    public static readonly DependencyProperty MaxValueProperty = DependencyProperty.Register(
        nameof(MaxValue), typeof(double), typeof(CvSparkChart),
        new PropertyMetadata(double.NaN, (d, _) => ((CvSparkChart)d).ApplyRange()));

    /// <summary>
    /// Pins the index axis to exactly [0, count-1] so the first and last values sit
    /// on the chart's left and right edges. Without it LiveCharts pads the range and
    /// the trace is drawn inset from any overlay (cursor, ruler) that uses the
    /// control's full width. Opt-in, so existing sparklines keep their look.
    /// </summary>
    public static readonly DependencyProperty FillWidthProperty = DependencyProperty.Register(
        nameof(FillWidth), typeof(bool), typeof(CvSparkChart),
        new PropertyMetadata(false, (d, _) => ((CvSparkChart)d).ApplyValues()));

    private readonly LineSeries<double> series;
    private readonly Axis valueAxis;
    private readonly Axis indexAxis;

    // Views give strokes as dark-palette hexes; light mode draws the matching light-palette hue.
    private static readonly Dictionary<string, string> LightStrokes = new(StringComparer.OrdinalIgnoreCase)
    {
        ["#2FF0D6"] = "#08907F",
        ["#7EF7E4"] = "#0DA894",
        ["#B07BFF"] = "#6F43CC",
        ["#FFB245"] = "#B06E06",
        ["#FF4D5E"] = "#CC2536",
        ["#35E6A1"] = "#13925F",
    };

    public CvSparkChart()
    {
        series = new LineSeries<double>
        {
            Values = Array.Empty<double>(),
            GeometrySize = 0,
            GeometryFill = null,
            GeometryStroke = null,
            LineSmoothness = 0.35,
            IsHoverable = false,
        };

        valueAxis = new Axis { IsVisible = false, MinLimit = 0 };
        indexAxis = new Axis { IsVisible = false };

        var chart = new CartesianChart
        {
            Series = new ISeries[] { series },
            XAxes = new[] { indexAxis },
            YAxes = new[] { valueAxis },
            TooltipPosition = TooltipPosition.Hidden,
            LegendPosition = LegendPosition.Hidden,
            DrawMargin = new Margin(0, 2, 0, 1),
            AnimationsSpeed = TimeSpan.Zero,
            Background = System.Windows.Media.Brushes.Transparent,
        };

        Content = chart;
        IsHitTestVisible = false;
        ApplyPaint();

        Loaded += (_, _) => { ThemeService.Changed += OnThemeChanged; ApplyPaint(); };
        Unloaded += (_, _) => ThemeService.Changed -= OnThemeChanged;
    }

    public IEnumerable<double>? Values
    {
        get => (IEnumerable<double>?)GetValue(ValuesProperty);
        set => SetValue(ValuesProperty, value);
    }

    public string StrokeHex
    {
        get => (string)GetValue(StrokeHexProperty);
        set => SetValue(StrokeHexProperty, value);
    }

    public bool ShowArea
    {
        get => (bool)GetValue(ShowAreaProperty);
        set => SetValue(ShowAreaProperty, value);
    }

    public double LineThickness
    {
        get => (double)GetValue(LineThicknessProperty);
        set => SetValue(LineThicknessProperty, value);
    }

    public double MaxValue
    {
        get => (double)GetValue(MaxValueProperty);
        set => SetValue(MaxValueProperty, value);
    }

    public bool FillWidth
    {
        get => (bool)GetValue(FillWidthProperty);
        set => SetValue(FillWidthProperty, value);
    }

    private void ApplyRange()
        => valueAxis.MaxLimit = double.IsNaN(MaxValue) ? null : MaxValue;

    private void ApplyValues()
    {
        var points = Values?.ToArray() ?? Array.Empty<double>();
        series.Values = points.Length >= 2 ? points : Array.Empty<double>();

        if (FillWidth && points.Length >= 2)
        {
            indexAxis.MinLimit = 0;
            indexAxis.MaxLimit = points.Length - 1;
        }
        else
        {
            indexAxis.MinLimit = null;
            indexAxis.MaxLimit = null;
        }
    }

    private void OnThemeChanged(string theme) => ApplyPaint();

    private void ApplyPaint()
    {
        var hex = StrokeHex;
        if (ThemeService.IsLight && hex is not null && LightStrokes.TryGetValue(hex, out var light))
            hex = light;
        if (!SKColor.TryParse(hex, out var colour))
        {
            colour = SKColor.Parse(ThemeService.IsLight ? "#08907F" : "#2FF0D6");
        }

        series.Stroke = new SolidColorPaint(colour) { StrokeThickness = (float)LineThickness };
        series.Fill = ShowArea
            ? new LinearGradientPaint(
                new[] { colour.WithAlpha(0x55), colour.WithAlpha(0x00) },
                new SKPoint(0.5f, 0f),
                new SKPoint(0.5f, 1f))
            : null;
    }
}
