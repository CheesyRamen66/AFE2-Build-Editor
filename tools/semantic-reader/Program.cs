using CUE4Parse.FileProvider;
using CUE4Parse.UE4.Assets.Exports.Texture;
using CUE4Parse.UE4.Versions;
using CUE4Parse_Conversion.Textures;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;
using Newtonsoft.Json.Serialization;
using SkiaSharp;
using UAssetAPI;
using UAssetAPI.UnrealTypes;

const string ReaderVersion = "0.3.0";

if (args is ["--version"])
{
    Console.WriteLine($"afe2-semantic-reader {ReaderVersion}");
    return 0;
}

if (args is ["--self-test-normalizer"])
{
    TexturePackageNormalizer.RunSelfTests();
    Console.WriteLine("texture package normalizer self-test passed");
    return 0;
}

if (args.Length != 5 || args[0] != "inspect")
{
    Console.Error.WriteLine(
        "usage: afe2-semantic-reader inspect REQUEST.json INPUT_ROOT OUTPUT.json ICON_ROOT"
    );
    return 2;
}

try
{
    var requestPath = Path.GetFullPath(args[1]);
    var inputRoot = Path.GetFullPath(args[2]);
    var outputPath = Path.GetFullPath(args[3]);
    var iconRoot = Path.GetFullPath(args[4]);
    var request = JsonConvert.DeserializeObject<ReaderRequest>(
        await File.ReadAllTextAsync(requestPath)
    ) ?? throw new InvalidDataException("request root was null");

    if (request.SchemaVersion != 1)
        throw new InvalidDataException("unsupported request schema");
    if (request.Assets is null || request.Icons is null ||
        request.Assets.Any(item => item is null) || request.Icons.Any(item => item is null))
        throw new InvalidDataException("request lists must contain non-null items");
    if (request.Assets.Select(item => item.PackagePath).Distinct(StringComparer.Ordinal).Count() != request.Assets.Count ||
        request.Assets.Select(item => item.MemberPath).Distinct(StringComparer.Ordinal).Count() != request.Assets.Count ||
        request.Icons.Select(item => item.PackagePath).Distinct(StringComparer.Ordinal).Count() != request.Icons.Count ||
        request.Icons.Select(item => item.MemberPath).Distinct(StringComparer.Ordinal).Count() != request.Icons.Count ||
        request.Icons.Select(item => item.OutputName).Distinct(StringComparer.Ordinal).Count() != request.Icons.Count)
        throw new InvalidDataException("request identities and icon outputs must be unique");

    Directory.CreateDirectory(iconRoot);
    var output = new ReaderOutput();
    foreach (var item in request.Assets.OrderBy(value => value.PackagePath, StringComparer.Ordinal))
    {
        try
        {
            ValidateAssetRequest(item);
            var path = ResolveContainedPath(inputRoot, item.MemberPath);
            var asset = new UAsset(path, EngineVersion.VER_UE4_27);
            var serialized = JObject.Parse(asset.SerializeJson(Formatting.None));
            output.Assets.Add(TrimAsset(item, serialized, asset));
        }
        catch (Exception exception)
        {
            output.Failures.Add(new ReaderFailure(
                "asset",
                item.PackagePath,
                $"parse-failed:{exception.GetType().Name}"
            ));
        }
    }

    if (request.Icons.Count > 0)
    {
        var providerRoot = Path.Combine(iconRoot, ".provider");
        if (Directory.Exists(providerRoot) || File.Exists(providerRoot))
            throw new InvalidDataException("icon provider staging path already existed");
        Directory.CreateDirectory(providerRoot);
        var preparedIcons = new List<IconRequest>();
        foreach (var item in request.Icons.OrderBy(value => value.PackagePath, StringComparer.Ordinal))
        {
            try
            {
                ValidateIconRequest(item);
                TexturePackageNormalizer.CopyNormalizedPackage(
                    inputRoot,
                    providerRoot,
                    item.MemberPath
                );
                preparedIcons.Add(item);
            }
            catch (Exception exception)
            {
                output.Failures.Add(new ReaderFailure(
                    "icon",
                    item.PackagePath,
                    $"decode-failed:{exception.GetType().Name}"
                ));
            }
        }

        using (var provider = new DefaultFileProvider(
            providerRoot,
            SearchOption.AllDirectories,
            new VersionContainer(EGame.GAME_UE4_27),
            StringComparer.OrdinalIgnoreCase
        ))
        {
        provider.Initialize();
        foreach (var item in preparedIcons)
        {
            try
            {
                ValidateIconRequest(item);
                var matchingKey = provider.Files.Keys.Single(
                    key => key.Replace('\\', '/').EndsWith(item.MemberPath, StringComparison.OrdinalIgnoreCase)
                );
                var package = provider.LoadPackage(matchingKey);
                var expectedName = Path.GetFileNameWithoutExtension(item.MemberPath);
                var texture = package.GetExports().OfType<UTexture2D>().Single(
                    value => string.Equals(value.Name, expectedName, StringComparison.Ordinal)
                );
                using var decoded = texture.Decode()
                    ?? throw new InvalidDataException("texture had no decodable mip");
                var destination = ResolveContainedPath(iconRoot, item.OutputName);
                using var encoded = new MemoryStream();
                if (!decoded.Encode(encoded, SKEncodedImageFormat.Png, 100))
                    throw new InvalidDataException("texture PNG encoding failed");
                await File.WriteAllBytesAsync(destination, encoded.ToArray());
                output.Icons.Add(new ReaderIcon(
                    item.PackagePath,
                    item.OutputName,
                    decoded.Width,
                    decoded.Height,
                    texture.PlatformData.PixelFormat.ToString()
                ));
            }
            catch (Exception exception)
            {
                output.Failures.Add(new ReaderFailure(
                    "icon",
                    item.PackagePath,
                    $"decode-failed:{exception.GetType().Name}"
                ));
            }
        }
        }
        Directory.Delete(providerRoot, recursive: true);
    }

    output.Assets.Sort((left, right) => StringComparer.Ordinal.Compare(left.PackagePath, right.PackagePath));
    output.Icons.Sort((left, right) => StringComparer.Ordinal.Compare(left.PackagePath, right.PackagePath));
    output.Failures.Sort((left, right) =>
    {
        var byPackage = StringComparer.Ordinal.Compare(left.PackagePath, right.PackagePath);
        return byPackage != 0 ? byPackage : StringComparer.Ordinal.Compare(left.Stage, right.Stage);
    });

    Directory.CreateDirectory(Path.GetDirectoryName(outputPath)!);
    await File.WriteAllTextAsync(
        outputPath,
        JsonConvert.SerializeObject(
            output,
            Formatting.None,
            new JsonSerializerSettings
            {
                ContractResolver = new CamelCasePropertyNamesContractResolver(),
            }
        )
    );
    Console.Error.WriteLine(
        $"semantic reader parsed {output.Assets.Count} asset(s), decoded {output.Icons.Count} icon(s), failures={output.Failures.Count}"
    );
    return 0;
}
catch (Exception exception)
{
    Console.Error.WriteLine($"semantic reader failed: {exception.GetType().Name}");
    return 1;
}

static void ValidateAssetRequest(AssetRequest item)
{
    if (!item.PackagePath.StartsWith("/Game/", StringComparison.Ordinal))
        throw new InvalidDataException("package path must be under /Game");
    if (!item.MemberPath.StartsWith("AFE2/Content/", StringComparison.Ordinal) ||
        !item.MemberPath.EndsWith(".uasset", StringComparison.OrdinalIgnoreCase))
        throw new InvalidDataException("member path was not a game asset");
    var canonicalMember = $"AFE2/Content/{item.PackagePath[6..]}.uasset";
    if (!string.Equals(item.MemberPath, canonicalMember, StringComparison.OrdinalIgnoreCase))
        throw new InvalidDataException("package and member paths did not identify the same asset");
}

static void ValidateIconRequest(IconRequest item)
{
    ValidateAssetRequest(new AssetRequest(item.PackagePath, item.MemberPath));
    if (Path.GetFileName(item.OutputName) != item.OutputName ||
        !item.OutputName.EndsWith(".png", StringComparison.OrdinalIgnoreCase))
        throw new InvalidDataException("icon output name was unsafe");
}

static string ResolveContainedPath(string root, string relative)
{
    var normalized = relative.Replace('/', Path.DirectorySeparatorChar);
    if (Path.IsPathRooted(normalized) || normalized.Split(Path.DirectorySeparatorChar).Contains(".."))
        throw new InvalidDataException("relative path was unsafe");
    var candidate = Path.GetFullPath(Path.Combine(root, normalized));
    var prefix = root.EndsWith(Path.DirectorySeparatorChar) ? root : root + Path.DirectorySeparatorChar;
    if (!candidate.StartsWith(prefix, StringComparison.Ordinal))
        throw new InvalidDataException("relative path escaped its root");
    return candidate;
}

static ReaderAsset TrimAsset(AssetRequest request, JObject serialized, UAsset asset)
{
    var imports = new JArray();
    foreach (var token in serialized["Imports"] as JArray ?? [])
    {
        if (token is not JObject source) continue;
        imports.Add(new JObject
        {
            ["classPackage"] = source["ClassPackage"]?.DeepClone(),
            ["className"] = source["ClassName"]?.DeepClone(),
            ["objectName"] = source["ObjectName"]?.DeepClone(),
            ["outerIndex"] = source["OuterIndex"]?.DeepClone(),
        });
    }

    var exports = new JArray();
    foreach (var token in serialized["Exports"] as JArray ?? [])
    {
        if (token is not JObject source) continue;
        var trimmed = new JObject
        {
            ["type"] = source["$type"]?.DeepClone(),
            ["objectName"] = source["ObjectName"]?.DeepClone(),
            ["classIndex"] = source["ClassIndex"]?.DeepClone(),
            ["superIndex"] = source["SuperIndex"]?.DeepClone(),
            ["templateIndex"] = source["TemplateIndex"]?.DeepClone(),
            ["data"] = source["Data"]?.DeepClone() ?? new JArray(),
        };
        if (request.IncludeScriptBytecode)
        {
            foreach (var (sourceName, outputName) in new[]
            {
                ("SuperStruct", "superStruct"),
                ("Children", "children"),
                ("LoadedProperties", "loadedProperties"),
                ("FunctionFlags", "functionFlags"),
                ("ScriptBytecode", "scriptBytecode"),
                ("ScriptBytecodeSize", "scriptBytecodeSize"),
                ("ScriptBytecodeRaw", "scriptBytecodeRaw"),
            })
            {
                if (source[sourceName] is JToken value)
                    trimmed[outputName] = value.DeepClone();
            }
        }
        exports.Add(trimmed);
    }

    return new ReaderAsset(
        request.PackagePath,
        request.MemberPath,
        asset.GetEngineVersion().ToString(),
        asset.IsUnversioned,
        asset.HasUnversionedProperties,
        imports,
        exports
    );
}

sealed record ReaderRequest(
    int SchemaVersion,
    List<AssetRequest> Assets,
    List<IconRequest> Icons
);

sealed record AssetRequest(
    string PackagePath,
    string MemberPath,
    bool IncludeScriptBytecode = false
);

sealed record IconRequest(string PackagePath, string MemberPath, string OutputName);

sealed record ReaderAsset(
    string PackagePath,
    string MemberPath,
    string EngineVersion,
    bool IsUnversioned,
    bool HasUnversionedProperties,
    JArray Imports,
    JArray Exports
);

sealed record ReaderIcon(
    string PackagePath,
    string OutputName,
    int Width,
    int Height,
    string PixelFormat
);

sealed record ReaderFailure(string Stage, string PackagePath, string Reason);

sealed class ReaderOutput
{
    public int SchemaVersion { get; } = 1;
    public string ReaderVersion { get; } = "0.3.0";
    public List<ReaderAsset> Assets { get; } = [];
    public List<ReaderIcon> Icons { get; } = [];
    public List<ReaderFailure> Failures { get; } = [];
}
