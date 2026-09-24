using AirQuality.Api.Data;
using AirQuality.Api.Dtos;
using Microsoft.AspNetCore.Mvc;
using Microsoft.EntityFrameworkCore;

namespace AirQuality.Api.Controllers;

[ApiController]
[Route(ApiRoutes.Base + "/sensors")]
public class SensorsController(AirQualityDbContext db) : ControllerBase
{
    // GET /api/v1/air-quality/sensors/SEN-01/readings?from=...&to=...
    [HttpGet("{sensorId}/readings")]
    public async Task<ReadingsResponse> GetReadings(string sensorId, [FromQuery] PeriodQuery period, CancellationToken ct)
    {
        return new ReadingsResponse(
            await db.ParticulateReadings.AsNoTracking().Where(r => r.SensorId == sensorId).InPeriod(period).ToListAsync(ct),
            await db.GasReadings.AsNoTracking().Where(r => r.SensorId == sensorId).InPeriod(period).ToListAsync(ct),
            await db.EnvironmentReadings.AsNoTracking().Where(r => r.SensorId == sensorId).InPeriod(period).ToListAsync(ct));
    }
}
