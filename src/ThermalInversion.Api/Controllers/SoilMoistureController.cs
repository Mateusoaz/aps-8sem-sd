using Microsoft.AspNetCore.Mvc;
using Microsoft.EntityFrameworkCore;
using ThermalInversion.Api.Data;
using ThermalInversion.Api.Dtos;
using ThermalInversion.Api.Models;

namespace ThermalInversion.Api.Controllers;

[ApiController]
[Route(ApiRoutes.Base + "/soil-moisture")]
public class SoilMoistureController(ThermalInversionDbContext db) : ControllerBase
{
    [HttpPost]
    public async Task<ActionResult<SoilMoistureReading>> Create(CreateSoilMoistureReadingRequest request, CancellationToken ct)
    {
        var reading = new SoilMoistureReading
        {
            StationId = request.StationId,
            SensorId = request.SensorId,
            SoilMoisturePercent = request.SoilMoisturePercent,
            Timestamp = request.Timestamp?.ToUniversalTime() ?? DateTimeOffset.UtcNow,
        };

        db.SoilMoistureReadings.Add(reading);
        await db.SaveChangesAsync(ct);

        return CreatedAtAction(nameof(GetById), new { id = reading.Id }, reading);
    }

    [HttpGet]
    public async Task<IReadOnlyList<SoilMoistureReading>> List(
        [FromQuery] string? stationId, [FromQuery] string? sensorId,
        [FromQuery] PeriodQuery period, CancellationToken ct)
    {
        var query = db.SoilMoistureReadings.AsNoTracking();
        if (stationId is not null) query = query.Where(r => r.StationId == stationId);
        if (sensorId is not null) query = query.Where(r => r.SensorId == sensorId);

        return await query.InPeriod(period).ToListAsync(ct);
    }

    [HttpGet("{id:long}")]
    public async Task<ActionResult<SoilMoistureReading>> GetById(long id, CancellationToken ct)
    {
        var reading = await db.SoilMoistureReadings.AsNoTracking().FirstOrDefaultAsync(r => r.Id == id, ct);
        return reading is null ? NotFound() : reading;
    }
}
