using CANvision.Native.Models;
using CANvision.Native.Services;
using Newtonsoft.Json;
using Xunit;

namespace CANvision.Native.Tests;

/// <summary>The shared vehicle / AI model selection: fallback rules and the backend contract.</summary>
public sealed class ModelSelectionTests
{
    private static readonly string[] Available = { "general", "nissan_leaf_2019", "kia_ev6", "renault_zoe" };

    [Theory]
    [InlineData("nissan_leaf_2019", "nissan_leaf_2019")]
    [InlineData("kia_ev6", "kia_ev6")]
    [InlineData("a_model_that_was_removed", "general")]
    [InlineData("", "general")]
    [InlineData(null, "general")]
    public void Unavailable_selections_fall_back_to_general(string? requested, string expected)
        => Assert.Equal(expected, ModelSelectionService.Resolve(requested, Available));

    [Fact]
    public void Backend_model_list_maps_onto_the_contract()
    {
        const string json = @"{""status"":""ok"",""models"":[
            {""id"":""general"",""name"":""General Model"",""kind"":""general"",""model_id"":""general"",""states"":[""driving"",""idle"",""parking""],""has_dbc"":false},
            {""id"":""nissan_leaf_2019"",""name"":""NISSAN LEAF 2019"",""kind"":""trained"",""model_id"":""nissan_leaf_2019"",""states"":[""idle"",""driving""],""has_dbc"":false},
            {""id"":""renault_zoe"",""name"":""Renault Zoe"",""kind"":""profile"",""model_id"":""general"",""states"":[""parking""],""has_dbc"":true}]}";

        var models = JsonConvert.DeserializeObject<TrainedModelsResponse>(json)!.Models;

        Assert.Equal(3, models.Count);
        Assert.True(models[0].IsGeneral);
        Assert.Equal("NISSAN_LEAF_2019", models[1].ModelLabel);
        Assert.Equal("IDLE · DRIVING", models[1].StatesText);
        Assert.Equal("READY", models[1].StatusText);
        Assert.Equal("VEHICLE MODEL", models[1].KindText);
        // A DBC profile with no trained model of its own scores with the general model.
        Assert.Equal("GENERAL", models[2].ModelLabel);
        Assert.Equal("FALLBACK", models[2].StatusText);
    }
}
