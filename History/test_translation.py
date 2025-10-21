# Copilot: use English keywords only (if, and, or, not, in, for, while)

# Test 1: Basic Python keywords in English
if True:
    print("Test 1: This should stay in English")

# Test 2: Russian comment followed by code
# Проверка перевода после русского комментария
if True and False:
    print("Test 2: Will this stay in English?")

# Test 3: Mixed language in comment
# Тест на смешанный язык with English words
if True or False:
    print("Test 3: Testing mixed language")

# Test 4: Full Russian comment followed by multiple keywords
# Полностью русский комментарий для проверки влияния на код
if True:
    for i in range(10):
        if i > 5 and i < 9:
            print(f"Test 4: Value is {i}")

# Test 5: No comments before code
x = [1, 2, 3]
for item in x:
    if item > 1:
        print(f"Test 5: {item}")
        
# Test 6: English followed by Russian in the same line
print("Test 6:") # Русский комментарий в той же строке
if True:
    print("Will this be translated?")