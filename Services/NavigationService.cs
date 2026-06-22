using System.Collections.ObjectModel;
using System.Linq;
using CANvision.Native.Models;
using CANvision.Native.ViewModels;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;

namespace CANvision.Native.Services;

public sealed class NavigationService : ObservableObject
{
    private readonly AppLogger logger;
    private readonly SectionViewModel homeSection;
    private readonly VehicleDataService vehicleDataService;
    private SectionViewModel currentSection;
    private NavigationStage stage;

    public NavigationService(
        AppLogger logger,
        HomeViewModel home,
        DashboardViewModel dashboard,
        TelemetryViewModel telemetry,
        DiagnosticsViewModel diagnostics,
        LogPlaybackViewModel playback,
        SettingsViewModel settings,
        PreviewViewModel preview,
        AnomalyIntelViewModel anomalyIntel,
        VehicleDataService vehicleDataService)
    {
        this.logger = logger;
        this.vehicleDataService = vehicleDataService;
        homeSection = home;
        Preview = preview;
        Tabs = new ObservableCollection<NavigationItemViewModel>(BuildTabs(dashboard, telemetry, diagnostics, playback, settings, anomalyIntel));

        PreviewSectionCommand = new RelayCommand<NavigationItemViewModel?>(PreviewSection);
        NavigateCommand = new RelayCommand<NavigationItemViewModel?>(Navigate);
        NavigateToSectionCommand = new RelayCommand<SectionKey>(NavigateToSection);
        EnterSystemCommand = new RelayCommand(EnterSystem, () => IsLandingVisible || IsHomeVisible || ReferenceEquals(CurrentSection, HomeSection));
        NavigateHomeCommand = new RelayCommand(NavigateHome, () => CanNavigateHome);
        BackToHubCommand = new RelayCommand(ExecuteBackToHub, () => IsSystemVisible);
        NavigateToGarageCommand = new RelayCommand(NavigateToGarage, () => !ReferenceEquals(CurrentSection, HomeSection) || !IsSystemVisible);
        currentSection = dashboard;
        stage = NavigationStage.Home;

        vehicleDataService.AppStateChanged += OnAppStateChanged;
        ApplyAppState(vehicleDataService.AppState);
    }

    private void OnAppStateChanged(AppState state)
    {
        ApplyAppState(state);
        OnPropertyChanged(nameof(IsAnalysisComplete));
    }

    private void ApplyAppState(AppState state)
    {
        bool unlocked = state == AppState.AnalysisComplete || state == AppState.LiveSession;
        foreach (var tab in Tabs)
        {
            // Settings is always accessible; live session and completed analysis unlock all screens.
            tab.IsUnlocked = unlocked || tab.Section.Key == SectionKey.Settings;
        }
        OnPropertyChanged(nameof(IsAnalysisComplete));
    }

    public bool IsAnalysisComplete => vehicleDataService.AppState == AppState.AnalysisComplete;

    public ObservableCollection<NavigationItemViewModel> Tabs { get; }

    public PreviewViewModel Preview { get; }

    public IRelayCommand<NavigationItemViewModel?> PreviewSectionCommand { get; }

    public IRelayCommand<NavigationItemViewModel?> NavigateCommand { get; }

    public IRelayCommand<SectionKey> NavigateToSectionCommand { get; }

    public IRelayCommand EnterSystemCommand { get; }

    public IRelayCommand NavigateHomeCommand { get; }

    public IRelayCommand BackToHubCommand { get; }

    public IRelayCommand NavigateToGarageCommand { get; }

    public HomeViewModel HomeSection => (HomeViewModel)homeSection;

    public SectionViewModel CurrentSection
    {
        get => currentSection;
        private set => SetProperty(ref currentSection, value);
    }

    public NavigationStage Stage
    {
        get => stage;
        private set => SetProperty(ref stage, value);
    }

    public bool IsHomeVisible => Stage == NavigationStage.Home;

    public bool IsLandingVisible => Stage == NavigationStage.Landing;

    public bool IsHubVisible => Stage == NavigationStage.Hub;

    public bool IsSystemVisible => Stage == NavigationStage.Interface;

    public bool CanNavigateHome => !IsHomeVisible;


    public void NavigateTo(string key)
    {
        if (!Enum.TryParse<SectionKey>(key, ignoreCase: true, out var sectionKey))
        {
            logger.Error($"Navigation target '{key}' is not a valid section key.");
            return;
        }

        NavigateToSection(sectionKey);
    }

    private static IEnumerable<NavigationItemViewModel> BuildTabs(
        DashboardViewModel dashboard,
        TelemetryViewModel telemetry,
        DiagnosticsViewModel diagnostics,
        LogPlaybackViewModel playback,
        SettingsViewModel settings,
        AnomalyIntelViewModel anomalyIntel)
    {
        var sections = new SectionViewModel[]
        {
            dashboard,
            telemetry,
            diagnostics,
            playback,
            settings,
            anomalyIntel,
        };

        foreach (var section in sections)
        {
            var descriptor = section.Descriptor ?? SectionCatalog.For(section.Key);
            if (descriptor is null) continue;
            yield return new NavigationItemViewModel(
                descriptor.ModuleCode,
                descriptor.Title,
                descriptor.MenuDescription,
                section);
        }
    }

    private void PreviewSection(NavigationItemViewModel? tab)
    {
        if (tab is null)
        {
            return;
        }

        ClearActiveTabs();
        SetCurrentSection(tab.Section);
        Preview.ActiveKey = tab.Section.Key;
        SetStage(NavigationStage.Hub);
        logger.Info($"Hub opened for {tab.Title}.");
    }

    private void Navigate(NavigationItemViewModel? tab)
    {
        if (tab is null)
            return;

        if (!tab.IsUnlocked)
        {
            logger.Info($"Navigation to {tab.Title} blocked — analysis not complete.");
            return;
        }

        SetActiveTab(tab);
        SetCurrentSection(tab.Section);
        SetStage(NavigationStage.Interface);
        logger.Info($"Navigation switched to {tab.Title}.");
    }

    private void EnterSystem()
    {
        var canExecuteSnapshot = IsLandingVisible || IsHomeVisible || ReferenceEquals(CurrentSection, HomeSection);
        logger.Info($"[NAV_TRACE] EnterSystem invoked. stage={Stage}, canExecuteSnapshot={canExecuteSnapshot}, isLanding={IsLandingVisible}, isHome={IsHomeVisible}, isHub={IsHubVisible}, isSystem={IsSystemVisible}, currentSection={CurrentSection?.Key}");
        if (!IsLandingVisible && !IsHomeVisible && !ReferenceEquals(CurrentSection, HomeSection))
        {
            logger.Info("[NAV_TRACE] EnterSystem early-returned due to stage/section guard.");
            return;
        }

        var tab = Tabs.FirstOrDefault(item => ReferenceEquals(item.Section, CurrentSection));
        tab ??= Tabs.FirstOrDefault();
        logger.Info($"[NAV_TRACE] EnterSystem resolved tab={(tab is null ? "null" : tab.Title)}.");
        if (tab is not null)
        {
            PreviewSection(tab);
            logger.Info($"[NAV_TRACE] EnterSystem completed. stage={Stage}, currentSection={CurrentSection?.Key}, isHub={IsHubVisible}, isSystem={IsSystemVisible}");
        }
        else
        {
            logger.Info("[NAV_TRACE] EnterSystem found no tab to preview.");
        }
    }

    private void NavigateHome()
    {
        if (IsHomeVisible)
        {
            return;
        }

        ClearActiveTabs();
        SetStage(NavigationStage.Home);
        logger.Info("Navigation returned to the landing screen.");
    }

    private void NavigateToGarage()
    {
        ClearActiveTabs();
        SetCurrentSection(HomeSection);
        SetStage(NavigationStage.Interface);
        logger.Info("Navigation returned to Garage.");
    }

    private void NavigateToSection(SectionKey key)
    {
        if (key == SectionKey.Telemetry)
        {
            logger.Info("Navigating to TelemetryView");
        }

        if (key == SectionKey.Home)
        {
            ClearActiveTabs();
            SetCurrentSection(HomeSection);
            SetStage(NavigationStage.Interface);
            logger.Info("Navigation initialized to Home.");
            return;
        }

        var tab = Tabs.FirstOrDefault(item => item.Section.Key == key);
        if (tab is null)
        {
            logger.Error($"Navigation target for section {key} was not found.");
            return;
        }

        Navigate(tab);
    }

    public void EnterLiveMode()
    {
        foreach (var tab in Tabs)
            tab.IsUnlocked = true;
        var dashboard = Tabs.FirstOrDefault(t => t.Section.Key == SectionKey.Dashboard);
        if (dashboard is null) return;
        SetActiveTab(dashboard);
        SetCurrentSection(dashboard.Section);
        SetStage(NavigationStage.Interface);
        logger.Info("EnterLiveMode: navigated directly to Dashboard.");
    }

    private void ExecuteBackToHub()
    {
        if (!IsSystemVisible) return;
        
        var tab = Tabs.FirstOrDefault(item => ReferenceEquals(item.Section, CurrentSection));
        PreviewSection(tab);
    }

    private void SetCurrentSection(SectionViewModel section)
    {
        if (ReferenceEquals(CurrentSection, section))
        {
            return;
        }

        CurrentSection = section;
        EnterSystemCommand.NotifyCanExecuteChanged();
        NavigateToGarageCommand.NotifyCanExecuteChanged();
    }

    private void SetStage(NavigationStage nextStage)
    {
        if (Stage == nextStage)
        {
            logger.Info($"[NAV_TRACE] SetStage no-op. stage already {Stage}.");
            return;
        }

        logger.Info($"[NAV_TRACE] SetStage transition {Stage} -> {nextStage}.");
        Stage = nextStage;
        OnPropertyChanged(nameof(IsHomeVisible));
        OnPropertyChanged(nameof(IsLandingVisible));
        OnPropertyChanged(nameof(IsHubVisible));
        OnPropertyChanged(nameof(IsSystemVisible));
        OnPropertyChanged(nameof(CanNavigateHome));
        EnterSystemCommand.NotifyCanExecuteChanged();
        NavigateHomeCommand.NotifyCanExecuteChanged();
        BackToHubCommand.NotifyCanExecuteChanged();
        NavigateToGarageCommand.NotifyCanExecuteChanged();
    }

    private void SetActiveTab(NavigationItemViewModel activeTab)
    {
        foreach (var item in Tabs)
        {
            item.IsActive = ReferenceEquals(item, activeTab);
        }
    }


    private void ClearActiveTabs()
    {
        foreach (var item in Tabs)
        {
            item.IsActive = false;
        }
    }
}
