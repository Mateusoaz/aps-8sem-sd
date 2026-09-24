using ThermalInversion.Api.Models;

namespace ThermalInversion.Api.Dtos;

/// <summary>Leituras de uma estação agrupadas por tipo.</summary>
public record ReadingsResponse(
    string StationId,
    IReadOnlyList<TemperatureProfileReading> TemperatureProfile,
    IReadOnlyList<SoilMoistureReading> SoilMoisture,
    IReadOnlyList<AirHumidityReading> AirHumidity,
    IReadOnlyList<AtmosphericPressureReading> AtmosphericPressure,
    IReadOnlyList<WindSpeedReading> WindSpeed);

/// <summary>Última leitura de cada tipo de uma estação.</summary>
public record LatestReadingsResponse(
    string StationId,
    TemperatureProfileReading? TemperatureProfile,
    SoilMoistureReading? SoilMoisture,
    AirHumidityReading? AirHumidity,
    AtmosphericPressureReading? AtmosphericPressure,
    WindSpeedReading? WindSpeed);

/// <summary>Perfil térmico de uma área numa janela de tempo. Médias null = sem leituras no período.</summary>
public record ThermalProfileResponse(
    string AreaId,
    DateTimeOffset From,
    DateTimeOffset To,
    int ReadingsCount,
    double? AverageSurfaceTemperatureC,
    double? AverageUpperTemperatureC,
    double? AverageGradientC, // média de (superior - superfície); positivo = ar de cima mais quente = inversão
    int InversionCount,
    bool InversionDetected);

/// <summary>Ocorrências de inversão de uma estação no período.</summary>
public record OccurrenceResponse(
    string StationId,
    string AreaId,
    int InversionCount,
    DateTimeOffset FirstDetectedAt,
    DateTimeOffset LastDetectedAt);
