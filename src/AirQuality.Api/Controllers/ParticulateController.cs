using AirQuality.Api.Data;
using AirQuality.Api.Dtos;
using AirQuality.Api.Models;
using AirQuality.Api.Services;
using Microsoft.AspNetCore.Mvc;
using Microsoft.EntityFrameworkCore;

namespace AirQuality.Api.Controllers;

[ApiController]
[Route(ApiRoutes.Base + "/particulate")]
public class ParticulateController(AirQualityDbContext db, AlertService alerts) : ControllerBase
{
    // POST /api/v1/air-quality/particulate
    [HttpPost]
    public async Task<ActionResult<ParticulateReading>> Create(CreateParticulateReadingRequest request, CancellationToken ct)
    {
        var reading = new ParticulateReading
        {
            StationId = request.StationId,
            SensorId = request.SensorId,
            AreaId = request.AreaId,
            Pm25 = request.Pm25,
            Pm10 = request.Pm10,
            Timestamp = request.Timestamp?.ToUniversalTime() ?? DateTimeOffset.UtcNow,
        };

        db.ParticulateReadings.Add(reading);
        await db.SaveChangesAsync(ct);
        await alerts.EvaluateParticulateAsync(reading, ct);

        return CreatedAtAction(nameof(GetById), new { id = reading.Id }, reading);
    }

    // GET /api/v1/air-quality/particulate?stationId=EST-01&from=...&limit=50
    [HttpGet]
    public async Task<IReadOnlyList<ParticulateReading>> List(
        [FromQuery] string? stationId, [FromQuery] string? sensorId, [FromQuery] string? areaId,
        [FromQuery] PeriodQuery period, CancellationToken ct)
    {
        var query = db.ParticulateReadings.AsNoTracking();
        if (stationId is not null) query = query.Where(r => r.StationId == stationId);
        if (sensorId is not null) query = query.Where(r => r.SensorId == sensorId);
        if (areaId is not null) query = query.Where(r => r.AreaId == areaId);

        return await query.InPeriod(period).ToListAsync(ct);
    }

    // GET /api/v1/air-quality/particulate/42
    [HttpGet("{id:long}")]
    public async Task<ActionResult<ParticulateReading>> GetById(long id, CancellationToken ct)
    {
        var reading = await db.ParticulateReadings.AsNoTracking().FirstOrDefaultAsync(r => r.Id == id, ct);
        return reading is null ? NotFound() : reading;
    }
}
