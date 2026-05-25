# Perseus directives — resolver location reference.
#
# Each @directive's resolve_* function lives in one of these modules.
# Some resolvers live outside this package due to dependency ordering:
#
#   @memory     → src/perseus/agora.py        (resolve_memory)
#   @health     → src/perseus/serve.py         (resolve_health)
#   @synthesize → src/perseus/serve.py         (synthesize_question)
#
# All other directives have their resolvers in the named module below.
