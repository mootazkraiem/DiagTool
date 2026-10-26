using System.Linq;
using CANvision.Native.Models;
using CANvision.Native.ViewModels;
using Newtonsoft.Json;
using Xunit;

namespace CANvision.Native.Tests;

/// <summary>
/// POST /api/signals/discover: the Telemetry channels come from the capture, and a
/// channel without a DBC is shown as an undecoded raw byte, never as a named signal.
/// </summary>
public sealed class SignalDiscoveryContractTests
{
    private const string RawJson = @"{""status"":""ok"",""model_id"":""jaguar_ipace"",""profile"":""jaguar_ipace"",
        ""decoder"":""raw"",""dbc_available"":false,""reason"":""no DBC for 'jaguar_ipace': raw payload bytes shown, not decoded"",
        ""frames"":15373,""duration_s"":5.1,
        ""channels"":[{""key"":""0x41:b3"",""label"":""0x41 · byte 3"",""unit"":""raw"",""can_id"":65,""decoded"":false,
          ""group"":""raw"",""samples"":510,""rate_hz"":100.0,""min"":2,""max"":200,""last"":171,""distinct"":90,
          ""times"":[0.0,0.5,1.0],""values"":[2.0,100.0,171.0]}]}";

    private const string DbcJson = @"{""status"":""ok"",""model_id"":""kia_ev6"",""profile"":""kia_ev6"",""decoder"":""dbc"",
        ""dbc_available"":true,""reason"":""decoded with the DBC of profile 'kia_ev6'"",""frames"":10,""duration_s"":1,
        ""channels"":[{""key"":""0x4F1:Vehicle_Speed"",""label"":""Vehicle_Speed"",""unit"":""km/h"",""can_id"":1265,""decoded"":true,
          ""group"":""speed"",""samples"":10,""rate_hz"":10.0,""min"":0,""max"":42.5,""last"":42.5,""distinct"":10,
          ""times"":[0,1],""values"":[0,42.5]}]}";

    [Fact]
    public void RawChannel_IsLabelledUndecoded()
    {
        var response = JsonConvert.DeserializeObject<SignalDiscoveryResponse>(RawJson)!;
        Assert.Equal("raw", response.Decoder);
        Assert.False(response.DbcAvailable);

        var item = new DiscoveredChannelItem(response.Channels.Single(), 0);
        Assert.Equal("0x41 · byte 3", item.Title);
        Assert.Equal("0xAB", item.ValueText);
        Assert.Equal("RAW", item.UnitText);
        Assert.Equal("UNDECODED · 100 HZ", item.MetaText);
        Assert.Equal(new[] { 2.0, 100.0, 171.0 }, item.Values);
    }

    [Fact]
    public void DecodedChannel_ShowsNameValueAndUnit()
    {
        var response = JsonConvert.DeserializeObject<SignalDiscoveryResponse>(DbcJson)!;
        var item = new DiscoveredChannelItem(response.Channels.Single(), 1);
        Assert.Equal("VEHICLE_SPEED", item.Title);
        Assert.Equal("42.5 km/h", item.ValueText);
        Assert.Equal("KM/H", item.UnitText);
        Assert.StartsWith("DBC · 0x4F1", item.MetaText);
        Assert.DoesNotContain("UNDECODED", item.MetaText);
    }
}
