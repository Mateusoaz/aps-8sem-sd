using Flooding.Api.Data;
using Flooding.Api.Dtos;
using Flooding.Api.Models;
using Microsoft.AspNetCore.Mvc;
using Microsoft.EntityFrameworkCore;

namespace Flooding.Api.Controllers;

[ApiController]
[Route(ApiRoutes.Base + "/rainfall")]
public class RainfallController(FloodingDbContext db) : ControllerBase
{
    [HttpPost]
    public async Task<ActionResult<RainfallReading>> Create(CreateRainfallReadingRequest request, CancellationToken ct)
    {
        var reading = new RainfallReading
        {
            MonitoringPointId = request.MonitoringPointId,
            SensorId = request.SensorId,
            RainfallMm = request.RainfallMm,
            Timestamp = request.Timestamp?.ToUniversalTime() ?? DateTimeOffset.UtcNow,
        };

        db.RainfallReadings.Add(reading);
        await db.SaveChangesAsync(ct);

        return CreatedAtAction(nameof(GetById), new { id = reading.Id }, reading);
    }

    [HttpGet]
    public async Task<IReadOnlyList<RainfallReading>> List(
        [FromQuery] string? monitoringPointId, [FromQuery] string? sensorId,
        [FromQuery] PeriodQuery period, CancellationToken ct)
    {
        var query = db.RainfallReadings.AsNoTracking();
        if (monitoringPointId is not null) query = query.Where(r => r.MonitoringPointId == monitoringPointId);
        if (sensorId is not null) query = query.Where(r => r.SensorId == sensorId);

        return await query.InPeriod(period).ToListAsync(ct);
    }

    [HttpGet("{id:long}")]
    public async Task<ActionResult<RainfallReading>> GetById(long id, CancellationToken ct)
    {
        var reading = await db.RainfallReadings.AsNoTracking().FirstOrDefaultAsync(r => r.Id == id, ct);
        return reading is null ? NotFound() : reading;
    }
}
