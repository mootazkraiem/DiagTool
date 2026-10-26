using System.ComponentModel;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;
using System.Windows.Media;
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
            SettleEntrance();

            // Apply the view model's current mode straight away. The state is
            // otherwise only applied when a property changes, so a Home that is
            // built while an import or analysis is already running kept the
            // XAML defaults and came up blank.
            ApplyChooserState(useTransitions: false);
            return;
        }
        entrancePlayed = true;
        if (TryFindResource("BootSequence") is Storyboard sequence)
        {
            // Not hit-testable, so a fast operator can already reach the chooser
            // underneath while the sequence finishes.
            BootOverlay.IsHitTestVisible = false;
            sequence.Begin(this, isControllable: true);

            // Development switch (--entrance-delay): hold the first frame, then play.
            if (Models.DevOptions.EntranceDelaySeconds > 0)
            {
                sequence.Pause(this);
                var hold = new System.Windows.Threading.DispatcherTimer
                {
                    Interval = System.TimeSpan.FromSeconds(Models.DevOptions.EntranceDelaySeconds),
                };
                hold.Tick += (_, _) => { hold.Stop(); sequence.Resume(this); };
                hold.Start();
            }
        }
    }

    // Card hover, started here rather than by EventTriggers in the XAML: MouseLeave also
    // fires while Home is being taken off screen with the mouse still over a card (after
    // RUN ANALYSIS or START LIVE SESSION), and the trigger then looked its storyboard's
    // targets up outside any name scope and threw ("OfflineHoverInSb" / "OfflineHoverGlow"
    // not found). Beginning against this view resolves the names in its own scope, and a
    // Home that is no longer on screen is not animated at all.
    private void Card_MouseEnter(object sender, MouseEventArgs e) => PlayCardHover(sender, entering: true);

    private void Card_MouseLeave(object sender, MouseEventArgs e) => PlayCardHover(sender, entering: false);

    private void PlayCardHover(object sender, bool entering)
    {
        if (!IsLoaded || !IsVisible)
            return;
        var prefix = ReferenceEquals(sender, LiveCard) ? "Live" : "Offline";
        if (TryFindResource(prefix + "HoverIn") is not Storyboard hoverIn
            || TryFindResource(prefix + "HoverOut") is not Storyboard hoverOut)
            return;
        if (entering)
        {
            hoverIn.Begin(this, isControllable: true);
            return;
        }
        hoverIn.Stop(this);          // ends the Live card's repeating bus pulse
        hoverOut.Begin(this, isControllable: true);
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

        ApplyChooserState(useTransitions: true);
    }

    /// <summary>
    /// Puts the chooser into the mode the view model is actually in.
    /// </summary>
    private void ApplyChooserState(bool useTransitions)
    {
        var vm = hookedVm;
        if (vm is null) return;

        var state = vm.IsLiveConnecting   ? "LiveConnecting"
                  : vm.IsOfflineImporting ? "OfflineImporting"
                  : vm.IsSelectingModel   ? "OfflineModelSelect"
                  : "ChooserMode";

        // Coming back to both cards, clear whatever a half-finished flip left
        // behind first. A transition that is interrupted - the operator clicks
        // again, or the analysis finishes mid-flip - holds its own animated
        // opacity on the card, which then outranks the state's value: the card
        // stayed invisible while still taking up its place in the row, which is
        // what left one card off-centre and, with both held down, an empty
        // screen under the analysis bar.
        if (state == "ChooserMode")
            SettleEntrance();

        VisualStateManager.GoToElementState(RootGrid, state, useTransitions);
        ApplyCardVisibility(state);
    }

    /// <summary>
    /// Decides which cards take up room in the row.
    ///
    /// This is done here rather than in the visual states because Visibility
    /// governs layout: a card that is merely transparent still occupies its half
    /// of the row and pushes the other card off centre. The states used to
    /// animate it, and an animated value outlives an interrupted transition, so
    /// a flip cut short by the analysis starting left the hidden card holding
    /// its place and the visible one sitting to the right of the screen.
    /// </summary>
    private void ApplyCardVisibility(string state)
    {
        // Only one card is on show while a session is being set up, and the row
        // centres whatever is left.
        var liveGone    = state is "OfflineImporting" or "OfflineModelSelect";
        var offlineGone = state is "LiveConnecting";

        SetVisibility(LiveCard, liveGone ? Visibility.Collapsed : Visibility.Visible);
        SetVisibility(OfflineCard, offlineGone ? Visibility.Collapsed : Visibility.Visible);
    }

    /// <summary>Sets Visibility so it stays set: any animation still holding the
    /// property is released first, otherwise it would outrank this value.</summary>
    private static void SetVisibility(UIElement element, Visibility visibility)
    {
        element.BeginAnimation(VisibilityProperty, null);
        element.Visibility = visibility;
    }

    /// <summary>
    /// Ends the entrance: every element it animates is released from animation
    /// and set to where the sequence leaves it. Releasing matters as much as the
    /// value, because a held animation wins over a plain assignment.
    /// </summary>
    private void SettleEntrance()
    {
        foreach (var element in new UIElement[]
                 {
                     AmbientWash, HomeHeader, HomeFooter,
                     LiveCard, LiveMeta, LiveStatus, LiveAction,
                     OfflineCard, OfflineMeta, OfflineStatus, OfflineAction,
                 })
        {
            element.BeginAnimation(OpacityProperty, null);
            element.Opacity = 1;
        }

        foreach (var shift in new[]
                 {
                     HomeHeaderShift, LiveCardShift, OfflineCardShift,
                     LiveHoverShift, OfflineHoverShift,
                 })
        {
            shift.BeginAnimation(TranslateTransform.YProperty, null);
            shift.Y = 0;
        }

        // Both cards belong in the row; ApplyCardVisibility takes one back out
        // when the mode calls for it.
        SetVisibility(LiveCard, Visibility.Visible);
        SetVisibility(OfflineCard, Visibility.Visible);
    }
}
