using System.Text.Json;
using ThermalInversion.Api.Services;
using Microsoft.Extensions.Options;
using RabbitMQ.Client;
using RabbitMQ.Client.Events;

namespace ThermalInversion.Api.Infrastructure;

/// <summary>
/// Consumidor da fila de avaliação de alertas: o processamento assíncrono da APS.
///
/// Todas as réplicas consomem a mesma fila (consumidores concorrentes): o RabbitMQ entrega cada mensagem
/// a uma só delas. A confirmação (ack) só é enviada depois de avaliar; se o pod morrer no meio, a mensagem
/// volta para a fila e outra réplica avalia. Por isso a entrega é "pelo menos uma vez", e o AlertService
/// é idempotente (não grava o mesmo alerta duas vezes).
/// </summary>
public class AlertConsumer(
    ReadingQueue queue,
    IServiceScopeFactory scopes,
    IOptions<QueueOptions> options,
    ILogger<AlertConsumer> logger) : BackgroundService
{
    private static readonly TimeSpan ReconnectDelay = TimeSpan.FromSeconds(5);

    protected override async Task ExecuteAsync(CancellationToken stoppingToken)
    {
        if (!queue.Enabled)
        {
            logger.LogInformation("Fila desligada: os alertas são avaliados dentro do POST.");
            return;
        }

        while (!stoppingToken.IsCancellationRequested)
        {
            try
            {
                using var channel = queue.OpenConsumerChannel();
                channel.BasicQos(prefetchSize: 0, prefetchCount: (ushort)Math.Clamp(options.Value.Prefetch, 1, 1000), global: false);

                var closed = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
                channel.ModelShutdown += (_, _) => closed.TrySetResult();

                var consumer = new AsyncEventingBasicConsumer(channel);
                consumer.Received += (_, delivery) => HandleAsync(channel, delivery, stoppingToken);
                channel.BasicConsume(ReadingQueue.QueueName, autoAck: false, consumer);
                logger.LogInformation("Consumindo a fila {Queue}.", ReadingQueue.QueueName);

                await closed.Task.WaitAsync(stoppingToken);
                logger.LogWarning("Canal com o RabbitMQ fechado. Reconectando em {Delay} s.", ReconnectDelay.TotalSeconds);
            }
            catch (OperationCanceledException) when (stoppingToken.IsCancellationRequested)
            {
                break;
            }
            catch (Exception ex)
            {
                logger.LogWarning("RabbitMQ indisponível ({Error}). Nova tentativa em {Delay} s.", ex.Message, ReconnectDelay.TotalSeconds);
            }

            try { await Task.Delay(ReconnectDelay, stoppingToken); }
            catch (OperationCanceledException) { break; }
        }
    }

    private async Task HandleAsync(IModel channel, BasicDeliverEventArgs delivery, CancellationToken ct)
    {
        try
        {
            // O corpo só é válido até o primeiro await: desserializa antes
            var message = JsonSerializer.Deserialize<ReadingMessage>(delivery.Body.Span)
                ?? throw new InvalidOperationException("Mensagem vazia.");

            using var scope = scopes.CreateScope();
            var alerts = scope.ServiceProvider.GetRequiredService<AlertService>();
            await alerts.EvaluateByIdAsync(message.ReadingId, ct);

            channel.BasicAck(delivery.DeliveryTag, multiple: false);
        }
        catch (Exception ex)
        {
            // Primeira falha: devolve para a fila (outra tentativa, talvez em outra réplica).
            // Se falhar de novo, descarta: uma mensagem com defeito não pode travar a fila para sempre.
            logger.LogError("Falha ao avaliar alerta (reentrega: {Redelivered}): {Error}", delivery.Redelivered, ex.Message);
            try { channel.BasicNack(delivery.DeliveryTag, multiple: false, requeue: !delivery.Redelivered); }
            catch (Exception) { /* canal já fechado: o broker devolve a mensagem sozinho */ }
        }
    }
}
