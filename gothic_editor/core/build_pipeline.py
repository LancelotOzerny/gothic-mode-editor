"""Sequential, fail-fast orchestration of the three independent operations."""
from .localization import tr


class BuildPipeline:
    def __init__(self, compilation):
        self.compilation=compilation

    def run(self,report=lambda _:None):
        for key,operation in [('compile',self.compilation.compile),('sync',self.compilation.synchronize),
                              ('launch',self.compilation.launch)]:
            report(tr('pipeline.stage',name=tr('pipeline.'+key)))
            result=operation(report)
            report(tr('pipeline.stage_success',name=tr('pipeline.'+key)))
        return result
