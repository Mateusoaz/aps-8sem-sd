using System.ComponentModel.DataAnnotations;
using AirQuality.Api.Data;
using AirQuality.Api.Dtos;
using AirQuality.Api.Infrastructure;
using Microsoft.AspNetCore.Mvc;
using Microsoft.EntityFrameworkCore;

namespace AirQuality.Api.Controllers;

[ApiController]
[Route(ApiRoutes.Base + "/areas")]
public class AreasController(AirQualityDbContext db, QueryCache cache) : ControllerBase
{
    // GET /api/v1/air-quality/areas/CENTRO/average?hours=24
    // Consulta agregada "média por região/período": seis médias sobre três tabelas. Fica no cache por TTL segundos.
    [HttpGet("{areaId}/average")]
    public async Task<AreaAverageResponse?> GetAverage(string areaId, [FromQuery, Range(1, 720)] int hours = 24, CancellationToken ct = default)
        => await cache.GetOrCreateAsync(Response, $"area-average:{areaId}:{hours}", () => ComputeAverageAsync(areaId, hours, ct));

    private async Task<AreaAverageResponse?> ComputeAverageAsync(string areaId, int hours, CancellationToken ct)
    {
        var to = DateTimeOffset.UtcNow;
        var from = to.AddHours(-hours);

        var particulate = db.ParticulateReadings.Where(r => r.AreaId == areaId && r.Timestamp >= from && r.Timestamp <= to);
        var gases = db.GasReadings.Where(r => r.AreaId == areaId && r.Timestamp >= from && r.Timestamp <= to);
        var environment = db.EnvironmentReadings.Where(r => r.AreaId == areaId && r.Timestamp >= from && r.Timestamp <= to);

        // O cast para double? faz a média de um conjunto vazio virar null em vez de lançar exceção
        return new AreaAverageResponse(
            areaId, from, to,
            await particulate.AverageAsync(r => (double?)r.Pm25, ct),
            await particulate.AverageAsync(r => (double?)r.Pm10, ct),
            await gases.AverageAsync(r => (double?)r.Co2, ct),
            await gases.AverageAsync(r => (double?)r.Tvoc, ct),
            await environment.AverageAsync(r => (double?)r.TemperatureC, ct),
            await environment.AverageAsync(r => (double?)r.HumidityPercent, ct));
    }
}
