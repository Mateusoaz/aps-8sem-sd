using Flooding.Api.Data;
using Flooding.Api.Dtos;
using Flooding.Api.Models;
using Flooding.Api.Services;
using Microsoft.AspNetCore.Mvc;
using Microsoft.EntityFrameworkCore;

namespace Flooding.Api.Controllers;

// Controller recebe JSON HTTP e delega persistência/regra de negócio às dependências injetadas.
[ApiController]
[Route(ApiRoutes.Base + "/water-level")]
public class WaterLevelController(FloodingDbContext db, AlertService alerts) : ControllerBase
{
    // POST /api/v1/flooding/water-level
    [HttpPost]
    public async Task<ActionResult<WaterLevelReading>> Create(CreateWaterLevelReadingRequest request, CancellationToken ct)
    {
        // Converte o contrato de entrada (DTO) em entidade de banco e normaliza horário para UTC.
        var reading = new WaterLevelReading
        {
            MonitoringPointId = request.MonitoringPointId,
            SensorId = request.SensorId,
            WaterLevelCm = request.WaterLevelCm,
            Timestamp = request.Timestamp?.ToUniversalTime() ?? DateTimeOffset.UtcNow,
        };

        // A gravação precede a regra para que ela encontre esta leitura ao consultar o histórico.
        db.WaterLevelReadings.Add(reading);
        await db.SaveChangesAsync(ct);
        // Avaliação síncrona: o POST só responde depois de checar se houve cruzamento da cota.
        await alerts.EvaluateWaterLevelAsync(reading, ct);

        // 201 Created inclui o recurso criado e a URL que permite consultá-lo pelo ID.
        return CreatedAtAction(nameof(GetById), new { id = reading.Id }, reading);
    }

    // GET /api/v1/flooding/water-level?monitoringPointId=PT-01&from=...&limit=50
    [HttpGet]
    public async Task<IReadOnlyList<WaterLevelReading>> List(
        [FromQuery] string? monitoringPointId, [FromQuery] string? sensorId,
        [FromQuery] PeriodQuery period, CancellationToken ct)
    {
        // AsNoTracking economiza trabalho em consultas que não vão alterar entidades.
        var query = db.WaterLevelReadings.AsNoTracking();
        if (monitoringPointId is not null) query = query.Where(r => r.MonitoringPointId == monitoringPointId);
        if (sensorId is not null) query = query.Where(r => r.SensorId == sensorId);

        // Os filtros são compostos em LINQ e executados pelo PostgreSQL quando materializados.
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
