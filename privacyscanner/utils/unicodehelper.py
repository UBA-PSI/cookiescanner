def eliminate_nullbytes(obj):
    if isinstance(obj, dict):
        return {
            eliminate_nullbytes(key): eliminate_nullbytes(value)
            for key, value in obj.items()
        }
    elif isinstance(obj, list):
        return [eliminate_nullbytes(x) for x in obj]
    elif isinstance(obj, str):
        return obj.replace('\u0000', '\uFFFD')
    else:
        return obj