using System.ComponentModel;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Media.Animation;
using CANvision.Native.ViewModels;

namespace CANvision.Native.UI;

public partial class HomeView : UserControl
{
    private HomeViewModel? hookedVm;

    // The entrance sequence belongs to starting CANvision, not to visiting Home:
    // navigating back later goes straight to the chooser.
    private static bool entrancePlayed;

    public HomeView()
    {
        InitializeComponent();
        DataContextChanged += OnDataContextChanged;
        Loaded += OnLoaded;
    }

    private void OnLoaded(object sender, RoutedEventArgs e)
    {
        if (entrancePlayed)
        {
            // Returning to Home later: no entrance, the chooser is simply there.
            AmbientWash.Opacity = 1;
            HomeHeader.Opacity = 1;
            HomeHeaderShift.Y = 0;
            LiveCard.Opacity = 1;
            OfflineCard.Opacity = 1;
            HomeFooter.Opacity = 1;
            return;
        }
        entrancePlayed = true;
        if (TryFindResource("BootSequence") is Storyboard sequence)
        {
            // Not hit-testable, so a fast operator can already reach the chooser
            // underneath while the sequence finishes.
            BootOverlay.IsHitTestVisible = false;
            sequence.Begin(this, isControllable: true);
        }
    }

    private void OnDataContextChanged(object sender, DependencyPropertyChangedEventArgs e)
    {
        if (hookedVm is not null)
            hookedVm.PropertyChanged -= OnVmPropertyChanged;

        hookedVm = DataContext as HomeViewModel;

        if (hookedVm is not null)
            hookedVm.PropertyChanged += OnVmPropertyChanged;
    }

    private void OnVmPropertyChanged(object? sender, PropertyChangedEventArgs e)
    {
        if (e.PropertyName is not (nameof(HomeViewModel.IsLiveConnecting)
            or nameof(HomeViewModel.IsOfflineImporting)
            or nameof(HomeViewModel.IsSelectingModel)))
            return;

        var vm = hookedVm;
        if (vm is null) return;

        var state = vm.IsLiveConnecting  ? "LiveConnecting"
                  : vm.IsOfflineImporting ? "OfflineImporting"
                  : vm.IsSelectingModel   ? "OfflineModelSelect"
                  : "ChooserMode";

        VisualStateManager.GoToElementState(RootGrid, state, useTransitions: true);
    }
}
