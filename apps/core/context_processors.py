from apps.scoring.profile import freelancer_config


def freelancer(request):
    return {"freelancer": freelancer_config()}
