FROM mcr.microsoft.com/dotnet/sdk:9.0 AS build
WORKDIR /src

COPY InversaoTermicaApi.csproj ./
RUN dotnet restore InversaoTermicaApi.csproj
COPY . ./
RUN dotnet publish InversaoTermicaApi.csproj -c Release -o /app/publish --no-restore /p:UseAppHost=false

FROM mcr.microsoft.com/dotnet/aspnet:9.0-bookworm-slim
RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/* \
    && mkdir -p /data \
    && chown app:app /data
WORKDIR /app
COPY --from=build /app/publish ./
ENV PORT=3004
ENV DB_PATH=/data/inversao_termica.db
EXPOSE 3004
USER app
ENTRYPOINT ["dotnet", "InversaoTermicaApi.dll"]
