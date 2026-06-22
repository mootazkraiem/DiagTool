using System.Windows.Controls;
using System.Windows.Input;
using System.Windows;
using CANvision.Native.ViewModels;

namespace CANvision.Native.UI;

public partial class PreviewView : UserControl
{
    public PreviewView()
    {
        InitializeComponent();
    }

    private void OnLoaded(object sender, RoutedEventArgs e)
    {
        this.Focus();
    }

    private void OnPreviewKeyDown(object sender, KeyEventArgs e)
    {
        if (DataContext is PreviewViewModel vm)
        {
            if (e.Key == Key.Up)
            {
                vm.SelectPrevious();
                e.Handled = true;
            }
            else if (e.Key == Key.Down)
            {
                vm.SelectNext();
                e.Handled = true;
            }
        }
    }
}
