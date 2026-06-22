using System.Windows.Controls;
using System.Diagnostics;

namespace CANvision.Native.UI;

public partial class TelemetryView : UserControl
{
    public TelemetryView()
    {
        InitializeComponent();
        Loaded += (_, _) =>
        {
            Debug.WriteLine("TelemetryView Loaded");
            Console.WriteLine("TelemetryView Loaded");
        };
    }
}
