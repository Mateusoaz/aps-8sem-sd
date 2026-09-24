using Flooding.Api.Data;
using Flooding.Api.Dtos;
using Flooding.Api.Models;
using Microsoft.AspNetCore.Mvc;
using Microsoft.EntityFrameworkCore;

namespace Flooding.Api.Controllers;

[ApiController]
[Route(ApiRoutes.Base + "/flow-rate")]
public class FlowRateController(FloodingDbContext db) : ControllerBase
{
    [HttpPost]
    public async Task<ActionResult<FlowRateReading>> Create(CreateFlowRateReadingRequest request, CancellationToken ct)
    {
        var reading = new FlowRateReading
        {
            MonitoringPointId = request.MonitoringPointId,
            SensorId = request.SensorId,
            FlowRateM3s = request.FlowRateM3s,
            Timestamp = request.Timestamp?.ToUniversalTime() ?? DateTimeOffset.UtcNow,
        };

        db.FlowRateReadings.Add(reading);
        await db.SaveChangesAsync(ct);

        return CreatedAtAction(nameof(GetById), new { id = reading.Id }, reading);
    }

    [HttpGet]
    public async Task<IReadOnlyList<FlowRateReading>> List(
        [FromQuery] string? monitoringPointId, [FromQuery] string? sensorId,
        [FromQuery] PeriodQuery period, CancellationToken ct)
    {
        var query = db.FlowRateReadings.AsNoTracking();
        if (monitoringPointId is not null) query = query.Where(r => r.MonitoringPointId == monitoringPointId);
        if (sensorId is not null) query = query.Where(r => r.SensorId == sensorId);

        return await query.InPeriod(period).ToListAsync(ct);
    }

    [HttpGet("{id:long}")]
    public async Task<ActionResult<FlowRateReading>> GetById(long id, CancellationToken ct)
    {
        var reading = await db.FlowRateReadings.AsNoTracking().FirstOrDefaultAsync(r => r.Id == id, ct);
        return reading is null ? NotFound() : reading;
    }
}
