using System.ComponentModel;
using CANvision.Native.Models;
using CANvision.Native.Scene;
using CANvision.Native.Services;

namespace CANvision.Native.ViewModels;

public sealed class MainWindowViewModel : ViewModelBase
{
    private readonly NavigationService navigationService;
    private bool useStartupFallbackState = true;
    private bool isSectionVisible = true;
    private SectionKey currentSectionKey = SectionKey.Home;

    public MainWindowViewModel(
        NavigationService navigationService,
        VehicleDataService vehicleDataService,
        BackgroundManager backgroundManager)
    {
        this.navigationService = navigationService;
        VehicleDataService = vehicleDataService;
        backgroundManager.LogDisabled();
        IsSectionVisible = true;
        CurrentSectionKey = SectionKey.Home;
        navigationService.PropertyChanged += NavigationServiceOnPropertyChanged;
        VehicleDataService.AppStateChanged += _ =>
        {
            OnPropertyChanged(nameof(IsAnalysisComplete));
            OnPropertyChanged(nameof(ShowEmptyState));
            OnPropertyChanged(nameof(ShowAnalysisBanner));
        };
        navigationService.HomeSection.PropertyChanged += (_, e) =>
        {
            if (e.PropertyName == nameof(HomeViewModel.AnalysisStatusText) ||
                e.PropertyName == nameof(HomeViewModel.AnalysisProgressPercent))
            {
                OnPropertyChanged(nameof(AnalysisBannerText));
                OnPropertyChanged(nameof(AnalysisBannerProgress));
                OnPropertyChanged(nameof(ShowAnalysisBanner));
            }
        };

        if (navigationService.IsSystemVisible || navigationService.IsHomeVisible || navigationService.IsHubVisible)
        {
            useStartupFallbackState = false;
        }
    }

    public NavigationService NavigationService => navigationService;

    public VehicleDataService VehicleDataService { get; }

    public HomeViewModel HomeSection => navigationService.HomeSection;

    public bool IsLandingScreenVisible => useStartupFallbackState ? false : !navigationService.IsSystemVisible && !navigationService.IsHubVisible;

    public bool IsHubVisible => useStartupFallbackState ? false : navigationService.IsHubVisible;

    public bool IsSectionVisible
    {
        get => useStartupFallbackState ? isSectionVisible : navigationService.IsSystemVisible;
        private set => SetProperty(ref isSectionVisible, value);
    }

    public PreviewViewModel HubSection => navigationService.Preview;

    public bool IsBackToCardsVisible => IsSectionVisible && CurrentSectionKey != SectionKey.Home;

    public bool IsGarageButtonVisible => IsSectionVisible || IsHubVisible;

    // Analysis state banners / empty-state guard
    public bool IsAnalysisComplete => VehicleDataService.AppState == Models.AppState.AnalysisComplete
                                   || VehicleDataService.AppState == Models.AppState.LiveSession;

    public bool ShowEmptyState =>
        !IsAnalysisComplete
        && CurrentSectionKey != SectionKey.Home
        && CurrentSectionKey != SectionKey.Settings;

    public bool ShowAnalysisBanner =>
        VehicleDataService.AppState == Models.AppState.Analyzing;

    public string AnalysisBannerText => navigationService.HomeSection.AnalysisStatusText;

    public string AnalysisBannerProgress => $"{navigationService.HomeSection.AnalysisProgressPercent:F0}%";

    public CommunityToolkit.Mvvm.Input.IRelayCommand NavigateToGarageCommand => navigationService.NavigateToGarageCommand;
    public CommunityToolkit.Mvvm.Input.IRelayCommand BackToCardsCommand => navigationService.BackToHubCommand;

    public SectionViewModel CurrentSection =>
        useStartupFallbackState
            ? navigationService.HomeSection
            : navigationService.IsHomeVisible
            ? navigationService.HomeSection
            : navigationService.CurrentSection;

    public SectionKey CurrentSectionKey
    {
        get => useStartupFallbackState
            ? currentSectionKey
            : navigationService.IsHomeVisible
            ? SectionKey.Home
            : navigationService.CurrentSection.Key;
        private set => SetProperty(ref currentSectionKey, value);
    }

    private void NavigationServiceOnPropertyChanged(object? sender, PropertyChangedEventArgs e)
    {
        if (e.PropertyName == nameof(NavigationService.CurrentSection) ||
            e.PropertyName == nameof(NavigationService.Stage))
        {
            useStartupFallbackState = false;
            OnPropertyChanged(nameof(HomeSection));
            OnPropertyChanged(nameof(HubSection));
            OnPropertyChanged(nameof(CurrentSection));
            OnPropertyChanged(nameof(CurrentSectionKey));
            OnPropertyChanged(nameof(IsLandingScreenVisible));
            OnPropertyChanged(nameof(IsHubVisible));
            OnPropertyChanged(nameof(IsSectionVisible));
            OnPropertyChanged(nameof(IsBackToCardsVisible));
            OnPropertyChanged(nameof(IsGarageButtonVisible));
            OnPropertyChanged(nameof(ShowEmptyState));
        }
    }
}
