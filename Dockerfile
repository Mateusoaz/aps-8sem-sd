# ============================================================
#  ESTAGIO 1 - build: compila o projeto usando o SDK completo
# ============================================================
FROM mcr.microsoft.com/dotnet/sdk:8.0 AS build
WORKDIR /src

# Copia so o .csproj primeiro e restaura as dependencias.
# Assim a camada de restore fica em cache e so e refeita quando
# o .csproj muda -- nao a cada alteracao no Program.cs.
COPY SensorApi.csproj ./
RUN dotnet restore

# Agora sim o codigo-fonte.
COPY . ./
RUN dotnet publish -c Release -o /app/publish --no-restore

# ============================================================
#  ESTAGIO 2 - runtime: imagem final, so com o necessario
# ============================================================
FROM mcr.microsoft.com/dotnet/aspnet:8.0 AS final
WORKDIR /app

# Necessario para o healthcheck HTTP definido no Compose.
USER root
RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

# Usuario nao-root ja existe nas imagens oficiais da Microsoft.
USER $APP_UID

# Traz apenas o resultado do publish. O SDK, o codigo-fonte
# e os arquivos intermediarios ficam para tras.
COPY --from=build /app/publish .

# Porta que a aplicacao escuta dentro do container.
ENV ASPNETCORE_HTTP_PORTS=8080
EXPOSE 8080

ENTRYPOINT ["dotnet", "SensorApi.dll"]
