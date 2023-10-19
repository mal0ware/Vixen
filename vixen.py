x = 0
y = 0
#defining function
def quadruple(x):
    if x == 4:
        y = x ** 2
    else:
        y = x * 4
    return y
#user input
x = quadruple(int(input("yo whatchu want x to be? ")))
print("okay bud imma do you a favor an quadruple that")
#generic statements
if y>16:
    print("bruh its over 16")
elif y==16:
    print("jackpot.")
else:
    print("my guy, its under 16")

print("at a total value of", x, sep=" ", end="\n")
print("have a good day!")
#yo this isnt actually vixen, you can delete all this code