using System.Text.Json;
using Microsoft.Extensions.Options;
using RabbitMQ.Client;

namespace ThermalInversion.Api.Infrastructure;

public class QueueOptions
{
    public const string SectionName = "Queue";

    /// <summary>Liga/desliga a fila sem recompilar (Queue__Enabled). Desligada, o alerta é avaliado dentro do POST.</summary>
    public bool Enabled { get; set; } = true;

    /// <summary>Quantas mensagens cada réplica recebe de uma vez, antes de confirmar (prefetch).</summary>
    public int Prefetch { get; set; } = 20;
}

/// <summary>Mensagem publicada a cada leitura gravada: só o id. O consumidor busca a leitura no banco.</summary>
public record ReadingMessage(long ReadingId);

/// <summary>
/// Conexão com o RabbitMQ (ConnectionStrings__RabbitMq) e publicação na fila de avaliação de alertas.
///
/// Quem abre e reabre a conexão é o AlertConsumer, em segundo plano. O POST só publica se a conexão já
/// estiver aberta: com o broker fora do ar, ele não espera timeout nenhum e avalia o alerta na hora.
/// A fila é durável e as mensagens são persistentes: sobrevivem a um restart do RabbitMQ.
/// </summary>
public sealed class ReadingQueue : IDisposable
{
    public const string QueueName = ApiRoutes.ServiceName + ".alert-evaluation";

    private readonly ConnectionFactory? _factory;
    private readonly ILogger<ReadingQueue> _logger;
    private readonly object _lock = new();
    private IConnection? _connection;
    private IModel? _publishChannel;

    public ReadingQueue(IConfiguration configuration, IOptions<QueueOptions> options, ILogger<ReadingQueue> logger)
    {
        _logger = logger;
        var uri = configuration.GetConnectionString("RabbitMq");
        if (!options.Value.Enabled || string.IsNullOrEmpty(uri))
            return;

        _factory = new ConnectionFactory
        {
            Uri = new Uri(uri),
            DispatchConsumersAsync = true,
            // A reconexão é feita pelo laço do AlertConsumer, não pela biblioteca
            AutomaticRecoveryEnabled = false,
            RequestedConnectionTimeout = TimeSpan.FromSeconds(3),
            ClientProvidedName = $"{ApiRoutes.ServiceName}@{AppInfo.Instance}",
        };
    }

    public bool Enabled => _factory is not null;

    public bool IsConnected => _connection is { IsOpen: true };

    /// <summary>Abre a conexão se preciso, declara a fila e devolve um canal novo (usado pelo consumidor).</summary>
    public IModel OpenConsumerChannel()
    {
        lock (_lock)
        {
            if (_connection is not { IsOpen: true })
            {
                _publishChannel = null;
                _connection?.Dispose();
                _connection = _factory!.CreateConnection();
                _logger.LogInformation("Conectado ao RabbitMQ.");
            }

            var channel = _connection.CreateModel();
            channel.QueueDeclare(QueueName, durable: true, exclusive: false, autoDelete: false);
            return channel;
        }
    }

    /// <summary>Publica o id da leitura. Devolve false se a fila estiver desligada ou fora do ar.</summary>
    public bool TryPublish(long readingId)
    {
        if (!IsConnected)
            return false;

        lock (_lock)
        {
            try
            {
                // Um canal não pode ser usado por duas threads ao mesmo tempo: daí o lock
                if (_publishChannel is not { IsOpen: true })
                    _publishChannel = _connection!.CreateModel();

                var properties = _publishChannel.CreateBasicProperties();
                properties.Persistent = true;
                properties.ContentType = "application/json";
                _publishChannel.BasicPublish(exchange: "", routingKey: QueueName, properties,
                    JsonSerializer.SerializeToUtf8Bytes(new ReadingMessage(readingId)));
                return true;
            }
            catch (Exception ex)
            {
                _logger.LogWarning("Falha ao publicar na fila ({Error}). Alerta avaliado no próprio POST.", ex.Message);
                _publishChannel = null;
                return false;
            }
        }
    }

    public void Dispose()
    {
        lock (_lock)
        {
            _publishChannel?.Dispose();
            _connection?.Dispose();
        }
    }
}
