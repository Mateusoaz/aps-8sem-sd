using Microsoft.AspNetCore.Mvc;
using Microsoft.EntityFrameworkCore;
using ThermalInversion.Api.Data;
using ThermalInversion.Api.Dtos;
using ThermalInversion.Api.Models;
using ThermalInversion.Api.Services;

namespace ThermalInversion.Api.Controllers;

[ApiController]
[Route(ApiRoutes.Base + "/temperature-profile")]
public class TemperatureProfileController(ThermalInversionDbContext db, AlertService alerts) : ControllerBase
{
    // POST /api/v1/thermal-inversion/temperature-profile
    [HttpPost]
    public async Task<ActionResult<TemperatureProfileReading>> Create(CreateTemperatureProfileReadingRequest request, CancellationToken ct)
    {
        var reading = new TemperatureProfileReading
        {
            StationId = request.StationId,
            AreaId = request.AreaId,
            SurfaceSensorId = request.SurfaceSensorId,
            UpperSensorId = request.UpperSensorId,
            SurfaceTemperatureC = request.SurfaceTemperatureC,
            UpperTemperatureC = request.UpperTemperatureC,
            Timestamp = request.Timestamp?.ToUniversalTime() ?? DateTimeOffset.UtcNow,
        };

        db.TemperatureProfiles.Add(reading);
        await db.SaveChangesAsync(ct);
        await alerts.EvaluateTemperatureProfileAsync(reading, ct);

        return CreatedAtAction(nameof(GetById), new { id = reading.Id }, reading);
    }

    // GET /api/v1/thermal-inversion/temperature-profile?stationId=EST-01&areaId=CENTRO&from=...
    [HttpGet]
    public async Task<IReadOnlyList<TemperatureProfileReading>> List(
        [FromQuery] string? stationId, [FromQuery] string? areaId, [FromQuery] string? sensorId,
        [FromQuery] PeriodQuery period, CancellationToken ct)
    {
        var query = db.TemperatureProfiles.AsNoTracking();
        if (stationId is not null) query = query.Where(r => r.StationId == stationId);
        if (areaId is not null) query = query.Where(r => r.AreaId == areaId);
        if (sensorId is not null) query = query.Where(r => r.SurfaceSensorId == sensorId || r.UpperSensorId == sensorId);

        return await query.InPeriod(period).ToListAsync(ct);
    }

    [HttpGet("{id:long}")]
    public async Task<ActionResult<TemperatureProfileReading>> GetById(long id, CancellationToken ct)
    {
        var reading = await db.TemperatureProfiles.AsNoTracking().FirstOrDefaultAsync(r => r.Id == id, ct);
        return reading is null ? NotFound() : reading;
    }
}
