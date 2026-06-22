using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;

namespace CANvision.Native.UI;

public partial class LogPlaybackView : UserControl
{
    public LogPlaybackView()
    {
        InitializeComponent();
    }

    private void TimelineGrid_SizeChanged(object sender, SizeChangedEventArgs e)
    {
        if (e.NewSize.Width > 0)
            TimelineScale.ScaleX = e.NewSize.Width / 920.0;
    }
}
