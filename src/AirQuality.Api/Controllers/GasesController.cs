using AirQuality.Api.Data;
using AirQuality.Api.Dtos;
using AirQuality.Api.Models;
using Microsoft.AspNetCore.Mvc;
using Microsoft.EntityFrameworkCore;

namespace AirQuality.Api.Controllers;

[ApiController]
[Route(ApiRoutes.Base + "/gases")]
public class GasesController(AirQualityDbContext db) : ControllerBase
{
    [HttpPost]
    public async Task<ActionResult<GasReading>> Create(CreateGasReadingRequest request, CancellationToken ct)
    {
        var reading = new GasReading
        {
            StationId = request.StationId,
            SensorId = request.SensorId,
            AreaId = request.AreaId,
            Co2 = request.Co2,
            Tvoc = request.Tvoc,
            Timestamp = request.Timestamp?.ToUniversalTime() ?? DateTimeOffset.UtcNow,
        };

        db.GasReadings.Add(reading);
        await db.SaveChangesAsync(ct);

        return CreatedAtAction(nameof(GetById), new { id = reading.Id }, reading);
    }

    [HttpGet]
    public async Task<IReadOnlyList<GasReading>> List(
        [FromQuery] string? stationId, [FromQuery] string? sensorId, [FromQuery] string? areaId,
        [FromQuery] PeriodQuery period, CancellationToken ct)
    {
        var query = db.GasReadings.AsNoTracking();
        if (stationId is not null) query = query.Where(r => r.StationId == stationId);
        if (sensorId is not null) query = query.Where(r => r.SensorId == sensorId);
        if (areaId is not null) query = query.Where(r => r.AreaId == areaId);

        return await query.InPeriod(period).ToListAsync(ct);
    }

    [HttpGet("{id:long}")]
    public async Task<ActionResult<GasReading>> GetById(long id, CancellationToken ct)
    {
        var reading = await db.GasReadings.AsNoTracking().FirstOrDefaultAsync(r => r.Id == id, ct);
        return reading is null ? NotFound() : reading;
    }
}
