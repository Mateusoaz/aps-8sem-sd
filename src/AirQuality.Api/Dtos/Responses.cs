using AirQuality.Api.Models;

namespace AirQuality.Api.Dtos;

/// <summary>Leituras agrupadas por tipo (usado em /stations/{id}/readings e /sensors/{id}/readings).</summary>
public record ReadingsResponse(
    IReadOnlyList<ParticulateReading> Particulate,
    IReadOnlyList<GasReading> Gases,
    IReadOnlyList<EnvironmentReading> Environment);

/// <summary>Última leitura de cada tipo de uma estação.</summary>
public record LatestReadingsResponse(
    string StationId,
    ParticulateReading? Particulate,
    GasReading? Gases,
    EnvironmentReading? Environment);

/// <summary>Médias de uma área (bairro) numa janela de tempo. null = sem leituras no período.</summary>
public record AreaAverageResponse(
    string AreaId,
    DateTimeOffset From,
    DateTimeOffset To,
    double? AveragePm25,
    double? AveragePm10,
    double? AverageCo2,
    double? AverageTvoc,
    double? AverageTemperatureC,
    double? AverageHumidityPercent);
