using System.Collections.Generic;
using System.Globalization;
using CANvision.Native.Models;

namespace CANvision.Native.ViewModels;

/// <summary>
/// Plain-English description of the loaded capture for the Dashboard's dataset card.
/// Every number comes from <see cref="DatasetFactsResponse"/> (measured from the file
/// or read from the model's corpus.json); nothing here is estimated.
/// </summary>
public static class DatasetCard
{
    private static readonly CultureInfo En = CultureInfo.GetCultureInfo("en-US");

    public static string Title(DatasetFactsResponse f) =>
        string.IsNullOrWhiteSpace(f.Vehicle) ? f.FileName : $"{f.Vehicle} · {f.FileName}";

    public static string Duration(double seconds) =>
        seconds < 60 ? string.Format(En, "{0:0.0} seconds", seconds)
        : seconds < 3600 ? string.Format(En, "{0} min {1:00} s", (int)(seconds / 60), (int)(seconds % 60))
        : string.Format(En, "{0} h {1:00} min", (int)(seconds / 3600), (int)(seconds % 3600 / 60));

    public static IReadOnlyList<DatasetFactItem> Facts(DatasetFactsResponse f)
    {
        var facts = new List<DatasetFactItem>
        {
            new("MESSAGES", f.Frames.ToString("N0", En)),
            new("DURATION", Duration(f.DurationS)),
            new("RATE", string.Format(En, "{0:N0} / s", f.RateHz)),
            new("MESSAGE TYPES", string.Format(En, "{0} CAN IDs", f.CanIds)),
        };
        if (!string.IsNullOrWhiteSpace(f.ModelVersion))
            facts.Add(new("AI MODEL", f.ModelVersion));
        facts.Add(new("ROLE", f.Role switch
        {
            "holdout" => "Test file (unseen)",
            "training" => "Training file",
            "outside" => "Not in model's set",
            _ => "Unknown",
        }));
        return facts;
    }

    public static IReadOnlyList<string> Paragraphs(DatasetFactsResponse f, bool hasLabels)
    {
        var car = string.IsNullOrWhiteSpace(f.Vehicle) || f.ModelId == "general" ? "the car" : $"the {f.Vehicle}";
        var list = new List<string>
        {
            string.Format(En,
                "This file is a recording of the messages the electronic units of {0} sent to each other over its internal network (the CAN bus). " +
                "It holds {1:N0} messages recorded over {2}, about {3:N0} messages per second, coming from {4} different message types (CAN IDs).",
                car, f.Frames, Duration(f.DurationS), f.RateHz, f.CanIds),
        };

        var training = string.Format(En, "{0} recording{1} ({2:N0} messages)",
            f.TrainingRecordings, f.TrainingRecordings == 1 ? "" : "s", f.TrainingFrames);
        switch (f.Role)
        {
            case "holdout":
                list.Add($"The AI model for this car ({f.ModelVersion}) never saw this recording while it was learning. " +
                         "It was kept aside on purpose as a test file, so what the dashboard shows is how the model reacts to traffic it has not seen before. " +
                         $"The model learned what normal traffic looks like from {training} of the same car.");
                break;
            case "training":
                list.Add($"This recording is one of the {training} the AI model ({f.ModelVersion}) learned from. " +
                         "Results on it show how the model sees traffic it already knows, not how it handles new traffic.");
                break;
            case "outside":
                list.Add($"This recording is not one of the files the selected AI model ({f.ModelVersion}) learned from or was tested on; " +
                         $"it learned from {training}.");
                break;
            default:
                list.Add("The selected AI model keeps no record of which recordings it learned from, so this file's role (training or test) is not known.");
                break;
        }

        list.Add(hasLabels
            ? "This file comes with a label file that marks the known attack periods, so the model's flags can be checked against it."
            : "There is no answer key for this file: nobody marked which messages, if any, are attacks. " +
              "When the model flags a message it means \"this looks unusual compared with the training recordings\", not \"this is a confirmed attack\".");
        return list;
    }
}

public sealed class DatasetFactItem
{
    public DatasetFactItem(string label, string value) { Label = label; Value = value; }
    public string Label { get; }
    public string Value { get; }
}
