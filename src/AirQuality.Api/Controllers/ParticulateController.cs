using AirQuality.Api.Data;
using AirQuality.Api.Dtos;
using AirQuality.Api.Models;
using AirQuality.Api.Services;
using Microsoft.AspNetCore.Mvc;
using Microsoft.EntityFrameworkCore;

namespace AirQuality.Api.Controllers;

// Controller recebe JSON HTTP e delega persistência/regra de negócio às dependências injetadas.
[ApiController]
[Route(ApiRoutes.Base + "/particulate")]
public class ParticulateController(AirQualityDbContext db, AlertService alerts) : ControllerBase
{
    // POST /api/v1/air-quality/particulate
    [HttpPost]
    public async Task<ActionResult<ParticulateReading>> Create(CreateParticulateReadingRequest request, CancellationToken ct)
    {
        // Converte o contrato de entrada (DTO) em entidade de banco e normaliza horário para UTC.
        var reading = new ParticulateReading
        {
            StationId = request.StationId,
            SensorId = request.SensorId,
            AreaId = request.AreaId,
            Pm25 = request.Pm25,
            Pm10 = request.Pm10,
            Timestamp = request.Timestamp?.ToUniversalTime() ?? DateTimeOffset.UtcNow,
        };

        // Primeiro persiste a leitura, para que a avaliação do alerta possa consultá-la no histórico.
        db.ParticulateReadings.Add(reading);
        await db.SaveChangesAsync(ct);
        // A regra roda dentro do próprio POST; por isso o cliente espera essa avaliação terminar.
        await alerts.EvaluateParticulateAsync(reading, ct);

        // 201 Created inclui o recurso criado e a URL que permite consultá-lo pelo ID.
        return CreatedAtAction(nameof(GetById), new { id = reading.Id }, reading);
    }

    // GET /api/v1/air-quality/particulate?stationId=EST-01&from=...&limit=50
    [HttpGet]
    public async Task<IReadOnlyList<ParticulateReading>> List(
        [FromQuery] string? stationId, [FromQuery] string? sensorId, [FromQuery] string? areaId,
        [FromQuery] PeriodQuery period, CancellationToken ct)
    {
        // AsNoTracking economiza trabalho em consultas que não vão alterar entidades.
        var query = db.ParticulateReadings.AsNoTracking();
        if (stationId is not null) query = query.Where(r => r.StationId == stationId);
        if (sensorId is not null) query = query.Where(r => r.SensorId == sensorId);
        if (areaId is not null) query = query.Where(r => r.AreaId == areaId);

        // Os filtros são compostos em LINQ e executados pelo PostgreSQL quando materializados.
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
