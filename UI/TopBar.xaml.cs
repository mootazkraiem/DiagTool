using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;
using System.Windows.Media;
using CANvision.Native.ViewModels;

namespace CANvision.Native.UI;

public partial class TopBar : UserControl
{
    public TopBar()
    {
        InitializeComponent();
    }

    public void SetNavigationEnabled(bool isEnabled)
    {
        IsEnabled = isEnabled;
        Opacity = isEnabled ? 1.0 : 0.55;
    }

    public void FocusActiveTab()
    {
        var activeButton = FindActiveButton(this) ?? FindFirstNavigationButton(this);
        activeButton?.Focus();
    }

    private void OnNavigationButtonKeyDown(object sender, KeyEventArgs e)
    {
        if (sender is not Button button)
        {
            return;
        }

        if (e.Key == Key.Enter || e.Key == Key.Space)
        {
            button.RaiseEvent(new RoutedEventArgs(Button.ClickEvent));
            e.Handled = true;
        }
    }

    private static Button? FindActiveButton(DependencyObject parent)
    {
        var childCount = VisualTreeHelper.GetChildrenCount(parent);
        for (var index = 0; index < childCount; index++)
        {
            var child = VisualTreeHelper.GetChild(parent, index);
            if (child is Button button && button.DataContext is NavigationItemViewModel item && item.IsActive)
            {
                return button;
            }

            var nestedButton = FindActiveButton(child);
            if (nestedButton is not null)
            {
                return nestedButton;
            }
        }

        return null;
    }

    private static Button? FindFirstNavigationButton(DependencyObject parent)
    {
        var childCount = VisualTreeHelper.GetChildrenCount(parent);
        for (var index = 0; index < childCount; index++)
        {
            var child = VisualTreeHelper.GetChild(parent, index);
            if (child is Button button)
            {
                return button;
            }

            var nestedButton = FindFirstNavigationButton(child);
            if (nestedButton is not null)
            {
                return nestedButton;
            }
        }

        return null;
    }
}
