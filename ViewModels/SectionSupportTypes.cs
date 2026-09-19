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

public sealed class MetricCardItem
{
    public MetricCardItem(string title, string value, string detail, string state)
    {
        Title = title;
        Value = value;
        Detail = detail;
        State = state;
    }

    public string Title { get; }
    public string Value { get; }
    public string Detail { get; }
    public string State { get; }
}

public sealed class StatusBadgeItem
{
    public StatusBadgeItem(string title, string value)
    {
        Title = title;
        Value = value;
    }

    public string Title { get; }
    public string Value { get; }
}

public sealed class AlertItem
{
    public AlertItem(string title, string detail, string state)
    {
        Title = title;
        Detail = detail;
        State = state;
    }

    public string Title { get; }
    public string Detail { get; }
    public string State { get; }
}

public sealed class SignalItem
{
    public SignalItem(
        string canId,
        string name,
        string value,
        string unit,
        string state,
        double freq = 0,
        double tdiff = 0,
        System.Windows.Media.PointCollection? trendPoints = null,
        string stateBrush = "#56F0AC",
        string canIdBrush = "#6E9090")
    {
        CanId = canId;
        Name = name;
        Value = value;
        Unit = unit;
        State = state;
        Frequency = freq;
        TimeDiff = tdiff;
        TrendPoints = trendPoints ?? new System.Windows.Media.PointCollection();
        StateBrush = stateBrush;
        CanIdBrush = canIdBrush;
    }

    public string CanId { get; }
    public string Name { get; }
    public string Value { get; }
    public string Unit { get; }
    public string State { get; }
    public double Frequency { get; }
    public double TimeDiff { get; }
    public System.Windows.Media.PointCollection TrendPoints { get; }
    public string StateBrush { get; }
    public string CanIdBrush { get; }
    public string FrequencyText => $"{Frequency:F1} Hz";
    public string TimeDiffText => $"{TimeDiff:F4}s";
}

public sealed class AttackTypeBarItem
{
    public string Label    { get; set; } = "";
    public int    Count    { get; set; }
    public double BarWidth { get; set; }
    public string Color    { get; set; } = "#00C8C8";
    public string CountText => Count.ToString();
}

public sealed class CanActivityItem
{
    public string CanId    { get; set; } = "0x000";
    public int    Count    { get; set; }
    public double AvgScore { get; set; }
    public double BarWidth { get; set; }
    public string BarColor { get; set; } = "#56F0AC";
    public string CountText => Count.ToString();
    public string ScoreText => $"{AvgScore:F2}";
}

public sealed class AxisLabelItem
{
    public AxisLabelItem(string text, double offset)
    {
        Text = text;
        Offset = offset;
    }

    public string Text { get; }
    public double Offset { get; }
}

public sealed class ReplayMarkerItem
{
    public ReplayMarkerItem(double offset, string label)
    {
        Offset = offset;
        Label = label;
    }

    public double Offset { get; }
    public string Label { get; }
}

public sealed class SubsystemStateItem
{
    public SubsystemStateItem(string name, string state, string stateBrush, string detail)
    {
        Name = name;
        State = state;
        StateBrush = stateBrush;
        Detail = detail;
    }

    public string Name { get; }
    public string State { get; }
    public string StateBrush { get; }
    public string Detail { get; }
}

public sealed class TelemetryEventItem
{
    public TelemetryEventItem(string timestamp, string severity, string source, string message)
    {
        Timestamp = timestamp;
        Severity = severity;
        Source = source;
        Message = message;
    }

    public string Timestamp { get; }
    public string Severity { get; }
    public string Source { get; }
    public string Message { get; }

    public string SeverityBrush => Severity switch
    {
        "CRITICAL"          => "#FF5050",
        "WARNING" or "WARN" => "#FFD94A",
        "INFO"              => "#56F0AC",
        _                   => "#6E9090",
    };
}

public sealed class SignalLegendItem
{
    public SignalLegendItem(string name, string colorHex)
    {
        Name = name;
        ColorHex = colorHex;
    }

    public string Name { get; }
    public string ColorHex { get; }
}

public sealed class FaultCodeItem
{
    public FaultCodeItem(string code, string description, string severity, string source, string timestamp)
    {
        Code = code;
        Description = description;
        Severity = severity;
        Source = source;
        Timestamp = timestamp;
    }

    public string Code { get; }
    public string Description { get; }
    public string Severity { get; }
    public string Source { get; }
    public string Timestamp { get; }
}

public sealed class DiagnosticDtcItem : ObservableObject
{
    private string status = "ACTIVE";

    public string FaultKey { get; set; } = string.Empty;
    public string Code { get; set; } = string.Empty;
    public string Description { get; set; } = string.Empty;
    public string Severity { get; set; } = "INFO";
    public string Source { get; set; } = "CAN_PIPELINE";
    public string CanId { get; set; } = "0x000";
    public DateTime Timestamp { get; set; } = DateTime.UtcNow;
    public DateTime FirstSeen { get; set; } = DateTime.UtcNow;
    public DateTime LastSeen { get; set; } = DateTime.UtcNow;
    public string AnomalyType { get; set; } = "GENERAL";
    public double ConfidenceScore { get; set; }
    public string Explanation { get; set; } = string.Empty;

    public string Status
    {
        get => status;
        set => SetProperty(ref status, value);
    }

    public string TimestampText => Timestamp.ToLocalTime().ToString("HH:mm:ss");
}

public sealed class PlaybackSessionItem
{
    public PlaybackSessionItem(string fileName, string date, string duration, string frameCount)
    {
        FileName = fileName;
        Date = date;
        Duration = duration;
        FrameCount = frameCount;
    }

    public string FileName { get; }
    public string Date { get; }
    public string Duration { get; }
    public string FrameCount { get; }
}

public sealed class PlaybackEventItem
{
    public PlaybackEventItem(string timestamp, string frameId, string data, string decodedSignal)
    {
        Timestamp = timestamp;
        FrameId = frameId;
        Data = data;
        DecodedSignal = decodedSignal;
    }

    public string Timestamp { get; }
    public string FrameId { get; }
    public string Data { get; }
    public string DecodedSignal { get; }
}

public sealed class ForensicTimelineMarker
{
    public ForensicTimelineMarker(string track, double left, double top, string label, string color)
    {
        Track = track;
        Left = left;
        Top = top;
        Label = label;
        Color = color;
    }

    public string Track { get; }
    public double Left { get; }
    public double Top { get; }
    public string Label { get; }
    public string Color { get; }
}

public sealed class ForensicTimelineWindow
{
    public ForensicTimelineWindow(string track, double left, double width, double top, string color)
    {
        Track = track;
        Left = left;
        Width = width;
        Top = top;
        Color = color;
    }

    public string Track { get; }
    public double Left { get; }
    public double Width { get; }
    public double Top { get; }
    public string Color { get; }
}

public sealed class CorrelationRowItem
{
    public CorrelationRowItem(string time, string canId, string eventText, string severity, string detection, string groundTruth, string details)
    {
        Time = time;
        CanId = canId;
        Event = eventText;
        Severity = severity;
        Detection = detection;
        GroundTruth = groundTruth;
        Details = details;
    }

    public string Time { get; }
    public string CanId { get; }
    public string Event { get; }
    public string Severity { get; }
    public string Detection { get; }
    public string GroundTruth { get; }
    public string Details { get; }
}

public sealed class ReplayEventRowItem
{
    public ReplayEventRowItem(string time, string severity, string source, string message)
    {
        Time = time;
        Severity = severity;
        Source = source;
        Message = message;
    }

    public string Time { get; }
    public string Severity { get; }
    public string Source { get; }
    public string Message { get; }
}

public sealed class SignalPlotSeriesItem
{
    public SignalPlotSeriesItem(string name, string color, System.Windows.Media.PointCollection points)
    {
        Name = name;
        Color = color;
        Points = points;
    }

    public string Name { get; }
    public string Color { get; }
    public System.Windows.Media.PointCollection Points { get; }
}

public sealed class AnalysisKpiItem : CommunityToolkit.Mvvm.ComponentModel.ObservableObject
{
    public AnalysisKpiItem(string label, string value, string meta, System.Windows.Media.PointCollection trendPoints, string color)
    {
        Label = label;
        _value = value;
        _meta = meta;
        TrendPoints = trendPoints;
        Color = color;
    }

    private string _value;
    private string _meta;

    public string Label { get; }
    public string Value
    {
        get => _value;
        set => SetProperty(ref _value, value);
    }
    public string Meta
    {
        get => _meta;
        set => SetProperty(ref _meta, value);
    }
    public System.Windows.Media.PointCollection TrendPoints { get; }
    public string Color { get; }
}

public sealed class ProfileItem
{
    public ProfileItem(string name, string state, string description)
    {
        Name = name;
        State = state;
        Description = description;
    }

    public string Name { get; }
    public string State { get; }
    public string Description { get; }
}

public sealed class SubsystemItem : ObservableObject
{
    private string state;

    public SubsystemItem(string name, string detail, string state)
    {
        Name = name;
        Detail = detail;
        this.state = state;
    }

    public string Name { get; }
    public string Detail { get; }
    
    public string State
    {
        get => state;
        set => SetProperty(ref state, value);
    }
}


