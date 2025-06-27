
def split_string_to_byte_chunks(data: str) -> list[bytes]:

    try:
        # Append CRLF and encode to ASCII
        data += '\x0d\x0a'
        byte_data = data.encode('ascii')
    except UnicodeEncodeError as e:
        raise ValueError("Input string contains non-ASCII characters.") from e

    # Initialize the result list
    chunks = []

    # Process in chunks of 8 bytes
    for i in range(0, len(byte_data), 8):
        chunk = byte_data[i:i+8]
        if len(chunk) < 8:
            # Pad with 0xFF if less than 8 bytes
            chunk += b'\xFF' * (8 - len(chunk))
        chunks.append(chunk)

    return chunks

try:
    data = "Hello world!"
    chunks = split_string_to_byte_chunks(data)
    for i, chunk in enumerate(chunks):
        print(f"Chunk {i}: {chunk}")
    print(f"\r\n")
except ValueError as e:
    print(f"Error: {e}")
    pass
    
try:
    data = "Café"
    chunks = split_string_to_byte_chunks(data)
    for i, chunk in enumerate(chunks):
        print(f"Chunk {i}: {chunk}")
    print(f"\r\n")
except ValueError as e:
    print(f"Error: {e}")
    pass
    
try:
    data = "$SCA: 0,100,0.31,0.23,0.00,0,0,1000,10000,0,0,30,8,6"
    chunks = split_string_to_byte_chunks(data)
    for i, chunk in enumerate(chunks):
        print(f"Chunk {i}: {chunk}, {chunk.hex()}")
    print(f"\r\n")
except ValueError as e:
    print(f"Error: {e}")
    pass
    
try:
    data = "$SCA: 0,100,0.31,0.23,0.00,0,0,0,10000,0,0,30,8,6"
    chunks = split_string_to_byte_chunks(data)
    for i, chunk in enumerate(chunks):
        print(f"Chunk {i}: {chunk}")
except ValueError as e:
    print(f"Error: {e}")
    pass


