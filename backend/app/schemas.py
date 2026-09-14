from pydantic import BaseModel


class SyncRequest(BaseModel):
    league_id: int
    season: int


class SetMyTeamRequest(BaseModel):
    team_id: int
