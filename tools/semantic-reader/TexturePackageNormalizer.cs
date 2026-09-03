using UAssetAPI;
using UAssetAPI.UnrealTypes;

internal static class TexturePackageNormalizer
{
    private const int CookedFlagOffset = 4;
    private const int PlatformSkipOffset = 16;
    private const int FNameSize = 8;

    internal static void CopyNormalizedPackage(
        string inputRoot,
        string providerRoot,
        string memberPath
    )
    {
        var sourceAsset = ResolveContainedPath(inputRoot, memberPath);
        var destinationAsset = ResolveContainedPath(providerRoot, memberPath);
        Directory.CreateDirectory(Path.GetDirectoryName(destinationAsset)!);

        var copiedFiles = new List<string>();
        foreach (var extension in new[] { ".uasset", ".uexp", ".ubulk", ".uptnl" })
        {
            var source = Path.ChangeExtension(sourceAsset, extension);
            if (!File.Exists(source)) continue;
            if (new FileInfo(source).LinkTarget is not null)
                throw new InvalidDataException("texture package companion was a symlink");
            var destination = Path.ChangeExtension(destinationAsset, extension);
            File.Copy(source, destination, overwrite: false);
            copiedFiles.Add(destination);
        }

        if (!File.Exists(destinationAsset))
            throw new FileNotFoundException("texture package omitted its uasset");

        var asset = new UAsset(
            destinationAsset,
            EngineVersion.VER_UE4_27,
            customSerializationFlags: CustomSerializationFlags.SkipPreloadDependencyLoading
        );
        if (asset.Exports.Count != 1)
            throw new InvalidDataException("texture package did not have exactly one export");
        var export = asset.Exports[0];
        var expectedName = Path.GetFileNameWithoutExtension(memberPath);
        if (!string.Equals(export.ObjectName.ToString(), expectedName, StringComparison.Ordinal))
            throw new InvalidDataException("texture export name did not match its package");
        var extras = export.Extras ?? throw new InvalidDataException("texture export omitted native data");
        var nameMap = asset.GetNameMapIndexList();
        var noneNameIndices = nameMap
            .Select((value, index) => (Name: value.ToString(), Index: index))
            .Where(item => string.Equals(item.Name, "None", StringComparison.Ordinal))
            .Select(item => item.Index)
            .ToArray();
        if (noneNameIndices.Length != 1)
            throw new InvalidDataException("texture package lacked one canonical None name");

        var matches = new List<(string Path, byte[] Payload)>();
        foreach (var path in copiedFiles)
        {
            var payload = File.ReadAllBytes(path);
            if (payload.AsSpan().IndexOf(extras) >= 0)
                matches.Add((path, payload));
        }
        if (matches.Count != 1)
            throw new InvalidDataException("texture native data did not have one package-file match");

        var (payloadPath, packagePayload) = matches[0];
        if (NormalizePlatformSkipOffset(
                packagePayload,
                extras,
                checked((long) export.SerialOffset),
                checked((long) export.SerialSize),
                noneNameIndices[0]
            ))
        {
            File.WriteAllBytes(payloadPath, packagePayload);
        }
    }

    internal static bool NormalizePlatformSkipOffset(
        byte[] packagePayload,
        byte[] nativeData,
        long serialOffset,
        long serialSize,
        int noneNameIndex
    )
    {
        if (nativeData.Length < PlatformSkipOffset + sizeof(long) + FNameSize)
            throw new InvalidDataException("texture native data was truncated");
        if (BitConverter.ToInt32(nativeData, CookedFlagOffset) != 1)
            throw new InvalidDataException("texture native data was not cooked");
        if (BitConverter.ToInt32(nativeData, nativeData.Length - FNameSize) != noneNameIndex ||
            BitConverter.ToInt32(nativeData, nativeData.Length - sizeof(int)) != 0)
            throw new InvalidDataException("texture native data lacked its terminal None name");
        if (serialOffset < 0 || serialSize < FNameSize)
            throw new InvalidDataException("texture export bounds were invalid");

        long exportEnd;
        try
        {
            exportEnd = checked(serialOffset + serialSize);
        }
        catch (OverflowException exception)
        {
            throw new InvalidDataException("texture export bounds overflowed", exception);
        }
        var desiredSkipOffset = exportEnd - FNameSize;
        var currentSkipOffset = BitConverter.ToInt64(nativeData, PlatformSkipOffset);
        if (currentSkipOffset < serialOffset || currentSkipOffset > desiredSkipOffset)
            throw new InvalidDataException("texture platform skip offset was outside its export");

        var firstMatch = packagePayload.AsSpan().IndexOf(nativeData);
        if (firstMatch < 0)
            throw new InvalidDataException("texture native data was absent from its package payload");
        if (packagePayload.AsSpan(firstMatch + 1).IndexOf(nativeData) >= 0)
            throw new InvalidDataException("texture native data was ambiguous in its package payload");
        if (currentSkipOffset == desiredSkipOffset)
            return false;

        BitConverter.TryWriteBytes(
            packagePayload.AsSpan(firstMatch + PlatformSkipOffset, sizeof(long)),
            desiredSkipOffset
        );
        return true;
    }

    internal static void RunSelfTests()
    {
        var native = new byte[40];
        BitConverter.TryWriteBytes(native.AsSpan(CookedFlagOffset, sizeof(int)), 1);
        BitConverter.TryWriteBytes(native.AsSpan(PlatformSkipOffset, sizeof(long)), 120L);
        BitConverter.TryWriteBytes(native.AsSpan(native.Length - FNameSize, sizeof(int)), 13);
        var package = new byte[80];
        native.CopyTo(package, 20);
        if (!NormalizePlatformSkipOffset(package, native, 100, 60, 13))
            throw new InvalidDataException("normalizer self-test did not repair an offset");
        if (BitConverter.ToInt64(package, 20 + PlatformSkipOffset) != 152L)
            throw new InvalidDataException("normalizer self-test wrote the wrong offset");

        var normalizedNative = package.AsSpan(20, native.Length).ToArray();
        if (NormalizePlatformSkipOffset(package, normalizedNative, 100, 60, 13))
            throw new InvalidDataException("normalizer self-test was not idempotent");

        AssertRejected(package, normalizedNative[..20], 100, 60, 13, "truncated");
        var nonTerminal = normalizedNative.ToArray();
        nonTerminal[^1] = 1;
        AssertRejected(nonTerminal, nonTerminal, 100, 60, 13, "terminal name");
        var ambiguous = normalizedNative.Concat(normalizedNative).ToArray();
        AssertRejected(ambiguous, normalizedNative, 100, 60, 13, "ambiguous");
        var outOfBounds = normalizedNative.ToArray();
        BitConverter.TryWriteBytes(outOfBounds.AsSpan(PlatformSkipOffset, sizeof(long)), 99L);
        AssertRejected(outOfBounds, outOfBounds, 100, 60, 13, "bounds");
    }

    private static void AssertRejected(
        byte[] packagePayload,
        byte[] nativeData,
        long serialOffset,
        long serialSize,
        int noneNameIndex,
        string label
    )
    {
        try
        {
            NormalizePlatformSkipOffset(
                packagePayload,
                nativeData,
                serialOffset,
                serialSize,
                noneNameIndex
            );
        }
        catch (InvalidDataException)
        {
            return;
        }
        throw new InvalidDataException($"normalizer self-test accepted {label} input");
    }

    private static string ResolveContainedPath(string root, string relative)
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
}
