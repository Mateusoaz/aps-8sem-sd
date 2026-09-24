using Flooding.Api.Models;

namespace Flooding.Api.Dtos;

/// <summary>Leituras de um ponto de monitoramento agrupadas por tipo.</summary>
public record ReadingsResponse(
    string MonitoringPointId,
    IReadOnlyList<WaterLevelReading> WaterLevel,
    IReadOnlyList<RainfallReading> Rainfall,
    IReadOnlyList<FlowRateReading> FlowRate);

/// <summary>Última leitura de cada tipo de um ponto de monitoramento.</summary>
public record LatestReadingsResponse(
    string MonitoringPointId,
    WaterLevelReading? WaterLevel,
    RainfallReading? Rainfall,
    FlowRateReading? FlowRate);
