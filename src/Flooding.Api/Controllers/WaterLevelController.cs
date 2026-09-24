using Flooding.Api.Data;
using Flooding.Api.Dtos;
using Flooding.Api.Models;
using Flooding.Api.Services;
using Microsoft.AspNetCore.Mvc;
using Microsoft.EntityFrameworkCore;

namespace Flooding.Api.Controllers;

[ApiController]
[Route(ApiRoutes.Base + "/water-level")]
public class WaterLevelController(FloodingDbContext db, AlertService alerts) : ControllerBase
{
    // POST /api/v1/flooding/water-level
    [HttpPost]
    public async Task<ActionResult<WaterLevelReading>> Create(CreateWaterLevelReadingRequest request, CancellationToken ct)
    {
        var reading = new WaterLevelReading
        {
            MonitoringPointId = request.MonitoringPointId,
            SensorId = request.SensorId,
            WaterLevelCm = request.WaterLevelCm,
            Timestamp = request.Timestamp?.ToUniversalTime() ?? DateTimeOffset.UtcNow,
        };

        db.WaterLevelReadings.Add(reading);
        await db.SaveChangesAsync(ct);
        await alerts.EvaluateWaterLevelAsync(reading, ct);

        return CreatedAtAction(nameof(GetById), new { id = reading.Id }, reading);
    }

    // GET /api/v1/flooding/water-level?monitoringPointId=PT-01&from=...&limit=50
    [HttpGet]
    public async Task<IReadOnlyList<WaterLevelReading>> List(
        [FromQuery] string? monitoringPointId, [FromQuery] string? sensorId,
        [FromQuery] PeriodQuery period, CancellationToken ct)
    {
        var query = db.WaterLevelReadings.AsNoTracking();
        if (monitoringPointId is not null) query = query.Where(r => r.MonitoringPointId == monitoringPointId);
        if (sensorId is not null) query = query.Where(r => r.SensorId == sensorId);

        return await query.InPeriod(period).ToListAsync(ct);
    }

    // GET /api/v1/flooding/water-level/42
    [HttpGet("{id:long}")]
    public async Task<ActionResult<WaterLevelReading>> GetById(long id, CancellationToken ct)
    {
        var reading = await db.WaterLevelReadings.AsNoTracking().FirstOrDefaultAsync(r => r.Id == id, ct);
        return reading is null ? NotFound() : reading;
    }
}
