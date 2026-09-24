using AirQuality.Api.Data;
using AirQuality.Api.Dtos;
using AirQuality.Api.Models;
using Microsoft.AspNetCore.Mvc;
using Microsoft.EntityFrameworkCore;

namespace AirQuality.Api.Controllers;

[ApiController]
[Route(ApiRoutes.Base + "/environment")]
public class EnvironmentController(AirQualityDbContext db) : ControllerBase
{
    [HttpPost]
    public async Task<ActionResult<EnvironmentReading>> Create(CreateEnvironmentReadingRequest request, CancellationToken ct)
    {
        var reading = new EnvironmentReading
        {
            StationId = request.StationId,
            SensorId = request.SensorId,
            AreaId = request.AreaId,
            TemperatureC = request.TemperatureC,
            HumidityPercent = request.HumidityPercent,
            Timestamp = request.Timestamp?.ToUniversalTime() ?? DateTimeOffset.UtcNow,
        };

        db.EnvironmentReadings.Add(reading);
        await db.SaveChangesAsync(ct);

        return CreatedAtAction(nameof(GetById), new { id = reading.Id }, reading);
    }

    [HttpGet]
    public async Task<IReadOnlyList<EnvironmentReading>> List(
        [FromQuery] string? stationId, [FromQuery] string? sensorId, [FromQuery] string? areaId,
        [FromQuery] PeriodQuery period, CancellationToken ct)
    {
        var query = db.EnvironmentReadings.AsNoTracking();
        if (stationId is not null) query = query.Where(r => r.StationId == stationId);
        if (sensorId is not null) query = query.Where(r => r.SensorId == sensorId);
        if (areaId is not null) query = query.Where(r => r.AreaId == areaId);

        return await query.InPeriod(period).ToListAsync(ct);
    }

    [HttpGet("{id:long}")]
    public async Task<ActionResult<EnvironmentReading>> GetById(long id, CancellationToken ct)
    {
        var reading = await db.EnvironmentReadings.AsNoTracking().FirstOrDefaultAsync(r => r.Id == id, ct);
        return reading is null ? NotFound() : reading;
    }
}
