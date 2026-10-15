#Requires -RunAsAdministrator
[CmdletBinding()]
param([switch]$VerifyOnly)

$ErrorActionPreference = 'Stop'
if ($env:COMPUTERNAME -ne 'GORGONZOLA' -or $env:USERNAME -ne 'funforgiven') {
    throw 'Run as the local funforgiven administrator on GORGONZOLA.'
}
$recordDirectory = 'C:\ProgramData\infra\gorgonzola'
New-Item -ItemType Directory -Path $recordDirectory -Force | Out-Null

# Microsoft documents these controls in the System, Privacy, Experience,
# Search, WindowsAI and Edge policy references linked from README.md.
# Pro supports required diagnostics as its minimum, not diagnostic-data-off.
$registry = [ordered]@{
    'HKLM:\SOFTWARE\Policies\Microsoft\Windows\DataCollection' = @{
        AllowTelemetry = 1; LimitDiagnosticLogCollection = 1
        LimitDumpCollection = 1; DoNotShowFeedbackNotifications = 1
    }
    'HKLM:\SOFTWARE\Policies\Microsoft\Windows\AdvertisingInfo' = @{DisabledByGroupPolicy = 1}
    'HKLM:\SOFTWARE\Policies\Microsoft\Windows\System' = @{
        EnableActivityFeed = 0; PublishUserActivities = 0; UploadUserActivities = 0
        AllowCrossDeviceClipboard = 0; AllowClipboardHistory = 0; EnableCdp = 0
    }
    'HKLM:\SOFTWARE\Policies\Microsoft\InputPersonalization' = @{AllowInputPersonalization = 0}
    'HKLM:\SOFTWARE\Policies\Microsoft\Windows\TextInput' = @{AllowLinguisticDataCollection = 0}
    'HKLM:\SOFTWARE\Policies\Microsoft\Windows\Windows Search' = @{
        AllowCortana = 0; AllowCloudSearch = 0; AllowSearchToUseLocation = 0
        EnableDynamicContentInWSB = 0; DisableWebSearch = 1; ConnectedSearchUseWeb = 0
    }
    'HKLM:\SOFTWARE\Policies\Microsoft\Windows\WindowsAI' = @{
        DisableAIDataAnalysis = 1; AllowRecallEnablement = 0; DisableClickToDo = 1
        DisableSettingsAgent = 1
    }
    'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\Paint' = @{
        DisableCocreator = 1; DisableGenerativeFill = 1
    }
    'HKLM:\SOFTWARE\Policies\Microsoft\Windows\LocationAndSensors' = @{
        DisableLocation = 1; DisableLocationScripting = 1; DisableSensors = 1
    }
    'HKLM:\SOFTWARE\Policies\Microsoft\FindMyDevice' = @{AllowFindMyDevice = 0}
    'HKLM:\SOFTWARE\Policies\Microsoft\Windows\OneDrive' = @{DisableFileSyncNGSC = 1}
    'HKLM:\SOFTWARE\Policies\Microsoft\Windows\SettingSync' = @{
        DisableSettingSync = 2; DisableSettingSyncUserOverride = 1
    }
    'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System' = @{NoConnectedUser = 3}
    'HKLM:\SOFTWARE\Policies\Microsoft\Windows\DeliveryOptimization' = @{DODownloadMode = 0}
    'HKLM:\SOFTWARE\Policies\Microsoft\Edge' = @{
        PersonalizationReportingEnabled = 0; SearchSuggestEnabled = 0
        SendSiteInfoToImproveServices = 0; UserFeedbackAllowed = 0
        BrowserSignin = 0; SyncDisabled = 1; BackgroundModeEnabled = 0
        StartupBoostEnabled = 0; EdgeShoppingAssistantEnabled = 0
        ShowMicrosoftRewards = 0; HubsSidebarEnabled = 0; HideFirstRunExperience = 1
    }
    'HKLM:\SYSTEM\CurrentControlSet\Control\Session Manager\Power' = @{HiberbootEnabled = 0}
    'HKCU:\SOFTWARE\Policies\Microsoft\Windows\CloudContent' = @{
        DisableTailoredExperiencesWithDiagnosticData = 1; DisableThirdPartySuggestions = 1
        DisableSpotlightCollectionOnDesktop = 1
    }
    'HKCU:\SOFTWARE\Policies\Microsoft\Windows\Explorer' = @{DisableSearchBoxSuggestions = 1}
    'HKCU:\SOFTWARE\Policies\Microsoft\Windows\WindowsCopilot' = @{TurnOffWindowsCopilot = 1}
    'HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\AdvertisingInfo' = @{Enabled = 0}
    'HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\Privacy' = @{TailoredExperiencesWithDiagnosticDataEnabled = 0}
    'HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\SearchSettings' = @{
        IsMSACloudSearchEnabled = 0; IsAADCloudSearchEnabled = 0
    }
    'HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\Explorer\Advanced' = @{
        Start_TrackProgs = 0; Start_TrackDocs = 0; TaskbarDa = 0; ShowCopilotButton = 0
        Start_IrisRecommendations = 0
    }
    'HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\ContentDeliveryManager' = @{
        ContentDeliveryAllowed = 0; FeatureManagementEnabled = 0; OemPreInstalledAppsEnabled = 0
        PreInstalledAppsEnabled = 0; PreInstalledAppsEverEnabled = 0; SilentInstalledAppsEnabled = 0
        SoftLandingEnabled = 0; SystemPaneSuggestionsEnabled = 0
        RotatingLockScreenEnabled = 0; RotatingLockScreenOverlayEnabled = 0
        'SubscribedContent-310093Enabled' = 0; 'SubscribedContent-338387Enabled' = 0
        'SubscribedContent-338388Enabled' = 0; 'SubscribedContent-338389Enabled' = 0
        'SubscribedContent-353694Enabled' = 0; 'SubscribedContent-353696Enabled' = 0
    }
    'HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\UserProfileEngagement' = @{ScoobeSystemSettingEnabled = 0}
    'HKCU:\SOFTWARE\Microsoft\InputPersonalization' = @{RestrictImplicitTextCollection = 1; RestrictImplicitInkCollection = 1}
    'HKCU:\SOFTWARE\Microsoft\InputPersonalization\TrainedDataStore' = @{HarvestContacts = 0}
    'HKCU:\SOFTWARE\Microsoft\Speech_OneCore\Settings\OnlineSpeechPrivacy' = @{HasAccepted = 0}
    'HKCU:\SOFTWARE\Microsoft\Siuf\Rules' = @{NumberOfSIUFInPeriod = 0; PeriodInNanoSeconds = 0}
    'HKCU:\Control Panel\International\User Profile' = @{HttpAcceptLanguageOptOut = 1}
}
$appPrivacy = @{}
foreach ($capability in @('AccountInfo', 'Calendar', 'CallHistory', 'Camera', 'Contacts',
        'DiagnosticInfo', 'Email', 'Location', 'Messaging', 'Microphone', 'Motion',
        'Notifications', 'Phone', 'Radios', 'Tasks', 'TrustedDevices')) {
    $appPrivacy["LetAppsAccess$capability"] = 2
}
$registry['HKLM:\SOFTWARE\Policies\Microsoft\Windows\AppPrivacy'] = $appPrivacy
$services = @('DiagTrack', 'dmwappushservice', 'WerSvc', 'lfsvc', 'MapsBroker')
$taskPaths = @(
    '\Microsoft\Windows\Application Experience\Microsoft Compatibility Appraiser',
    '\Microsoft\Windows\Application Experience\ProgramDataUpdater',
    '\Microsoft\Windows\Customer Experience Improvement Program\Consolidator',
    '\Microsoft\Windows\Customer Experience Improvement Program\UsbCeip',
    '\Microsoft\Windows\Feedback\Siuf\DmClient',
    '\Microsoft\Windows\Feedback\Siuf\DmClientOnScenarioDownload'
)
$tasks = @(Get-ScheduledTask | Where-Object { ($_.TaskPath + $_.TaskName) -in $taskPaths })
$consumerApps = @('Microsoft.Copilot', 'Microsoft.WindowsFeedbackHub', 'Microsoft.BingNews',
    'Microsoft.BingWeather', 'MicrosoftWindows.Client.WebExperience')
$sleepGroup = '238c9fa8-0aad-41ed-83f4-97be242c8f20'
$powerSettings = @(
    @($sleepGroup, '29f6c1db-86da-48c5-9fdb-f2b67b1f44da'), # sleep
    @($sleepGroup, '9d7815a6-7ee4-497e-8888-515a05f02364'), # hibernate
    @($sleepGroup, '94ac6d29-73ce-41a6-809f-6363ba21b47e'), # hybrid sleep
    @($sleepGroup, '7bc4a2f9-d8fc-4469-b07b-33eb785aaca0'), # unattended sleep
    @('7516b95f-f776-4464-8c53-06167f40cc99', '3c0bc021-c8a8-4e07-a973-6b14cbcb2b7e'), # display
    @('0012ee47-9041-4b5d-9b77-535fba8b1442', '6738e2c4-e8a5-4a42-b16a-e040e769756e') # disk idle
)
function Read-RegistryValue($Path, $Name) {
    if (Test-Path -LiteralPath $Path) {
        (Get-Item -LiteralPath $Path).GetValue($Name, $null)
    }
}
function Read-RegistryValues {
    foreach ($path in $registry.Keys) {
        foreach ($name in $registry[$path].Keys) {
            $value = Read-RegistryValue $path $name
            [pscustomobject]@{Path = $path; Name = $name; Value = $value; Expected = $registry[$path][$name]}
        }
    }
}
function Invoke-PowerSetting {
    & powercfg.exe @args
    if ($LASTEXITCODE -ne 0) { throw "powercfg failed: $args" }
}
if (-not $VerifyOnly) {
    $before = Join-Path $recordDirectory ('settings-before-' + (Get-Date -Format 'yyyyMMdd-HHmmss') + '.json')
    @{
        Registry = @(Read-RegistryValues)
        Services = @(Get-Service -Name $services -ErrorAction SilentlyContinue | Select-Object Name, Status, StartType)
        Tasks = @($tasks | Select-Object TaskPath, TaskName, State)
        Defender = Get-MpPreference | Select-Object MAPSReporting, SubmitSamplesConsent, DisableBlockAtFirstSeen
    } | ConvertTo-Json -Depth 6 | Set-Content -Encoding UTF8 $before
    powercfg.exe /query | Set-Content -Encoding UTF8 ($before + '.power.txt')
    Invoke-PowerSetting /setactive SCHEME_BALANCED
    foreach ($setting in $powerSettings) {
        Invoke-PowerSetting /setacvalueindex SCHEME_CURRENT $setting[0] $setting[1] 0
        Invoke-PowerSetting /setdcvalueindex SCHEME_CURRENT $setting[0] $setting[1] 0
    }
    Invoke-PowerSetting /hibernate off
    Invoke-PowerSetting /setactive SCHEME_CURRENT
    foreach ($path in $registry.Keys) {
        if (-not (Test-Path -LiteralPath $path)) {
            New-Item -Path $path -Force | Out-Null
        }
        foreach ($name in $registry[$path].Keys) {
            try {
                New-ItemProperty -LiteralPath $path -Name $name -Value $registry[$path][$name] -PropertyType DWord -Force | Out-Null
            } catch {
                Write-Warning "Could not set $path / $name : $_"
            }
        }
    }
    foreach ($package in Get-AppxPackage -AllUsers | Where-Object Name -In $consumerApps) {
        Remove-AppxPackage -Package $package.PackageFullName -AllUsers
    }
    foreach ($package in Get-AppxProvisionedPackage -Online | Where-Object DisplayName -In $consumerApps) {
        Remove-AppxProvisionedPackage -Online -PackageName $package.PackageName | Out-Null
    }
    $recall = Get-WindowsOptionalFeature -Online -FeatureName Recall -ErrorAction SilentlyContinue
    if ($recall -and $recall.State -eq 'Enabled') {
        Disable-WindowsOptionalFeature -Online -FeatureName Recall -NoRestart | Out-Null
    }
    Write-Host "Applied power/privacy settings; original values saved to $before"
}
$activeScheme = [regex]::Match((powercfg.exe /getactivescheme), '[0-9a-fA-F-]{36}').Value
$powerMismatches = @(foreach ($setting in $powerSettings) {
    $path = "HKLM:\SYSTEM\CurrentControlSet\Control\Power\User\PowerSchemes\$activeScheme\$($setting[0])\$($setting[1])"
    foreach ($name in @('ACSettingIndex', 'DCSettingIndex')) {
        if ((Read-RegistryValue $path $name) -ne 0) {
            "$($setting[1]):$name"
        }
    }
})
$values = @(Read-RegistryValues)
$preferences = Get-MpPreference
$record = [ordered]@{
    VerifiedAt = (Get-Date).ToUniversalTime().ToString('o')
    Computer = $env:COMPUTERNAME
    PowerScheme = $activeScheme
    PowerMismatches = $powerMismatches
    HibernateFilePresent = Test-Path 'C:\hiberfil.sys'
    RegistryValuesChecked = $values.Count
    RegistryMismatches = @($values | Where-Object { $_.Value -ne $_.Expected })
    DiagnosticServices = @(Get-Service -Name $services -ErrorAction SilentlyContinue | Select-Object Name, Status, StartType)
    FeedbackTasks = @(Get-ScheduledTask | Where-Object { ($_.TaskPath + $_.TaskName) -in $taskPaths } | Select-Object TaskName, State)
    RemainingConsumerApps = @(Get-AppxPackage -AllUsers | Where-Object Name -In $consumerApps | Select-Object Name)
    DefenderSamplesConsent = $preferences.SubmitSamplesConsent
    DefenderCloudReporting = $preferences.MAPSReporting
    DefenderRealtimeEnabled = (Get-MpComputerStatus).RealTimeProtectionEnabled
    UpdateServiceDisabled = (Get-Service wuauserv).StartType -eq 'Disabled'
    Network = @(Get-NetAdapter -Physical | Select-Object Name, Status, MacAddress, LinkSpeed)
    Recall = [string](Get-WindowsOptionalFeature -Online -FeatureName Recall -ErrorAction SilentlyContinue).State
}
$record | ConvertTo-Json -Depth 6 | Set-Content -Encoding UTF8 (Join-Path $recordDirectory 'settings-verified.json')
$record | ConvertTo-Json -Depth 6
if ($record.RegistryMismatches.Count -or $powerMismatches.Count -or $record.HibernateFilePresent -or
    $record.RemainingConsumerApps.Count -or
    -not $record.DefenderRealtimeEnabled -or $record.UpdateServiceDisabled) {
    throw 'Some settings did not take effect; inspect settings-verified.json.'
}
